# Anveshq: Fluxmind Backend

Anveshq is a Python market-intelligence backend with:
- Weekly universe build (`master-*.json` snapshots)
- Daily momentum scan and ranking
- Weekly email report
- Local SQLite persistence with automated cleanup and optimization

## Architecture

```text
                +------------------------------+
                | GitHub Actions Schedules     |
                | daily / weekly / monthly     |
                +--------------+---------------+
                               |
                               v
   +-------------------+   +--------------------------+   +----------------------+
   | Weekly Rootset    |   | Daily Fluxmind Scanner   |   | Weekly Email Report  |
   | src.master_builder|   | src.main                 |   | src.email_report     |
   +---------+---------+   +------------+-------------+   +-----------+----------+
             |                          |                             |
             v                          v                             v
      data/master/*.json        data/anveshq.db (SQLite)      reads SQLite + sends email
      + master-latest.json      (committed to repo)
```

## Project Layout

```text
Anveshq/
|- Backend/
|  |- src/
|  |  |- config.py
|  |  |- database.py
|  |  |- cleanup_service.py
|  |  |- main.py
|  |  |- master_builder.py
|  |  |- email_report.py
|  |  |- services.py
|  |- requirements.txt
|  |- tests/
|- data/
|  |- anveshq.db
|  |- master/
|- .github/workflows/
```

## SQLite Migration Notes

The project now uses SQLite instead of PostgreSQL/Supabase.

- Production DB: `data/anveshq.db`
- Test DB: `data/test_anveshq.db`
- SQLite pragmas are enabled on connect:
  - `journal_mode=WAL`
  - `synchronous=NORMAL`
  - `cache_size=-10000`
  - `foreign_keys=ON`
  - `temp_store=MEMORY`

`Backend/src/config.py` provides path-based settings and computed SQLite URLs.

## Data Retention Policies

- `momentum_ranks`: retain 104 weeks
- `errors`: retain 90 days
- `data/master/`: keep `master-latest.json` + last 7 snapshots
- `users`, `verification_codes`: retained permanently

Cleanup service runs `VACUUM`/`ANALYZE` after cleanup to keep DB compact.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
cd Backend
python -m pip install -r requirements.txt
```

3. Configure environment variables in `Backend/.env` (optional if defaults are acceptable):
- `MODE=DEV|PROD|TEST`
- `DATABASE_PATH=data/anveshq.db`
- `TEST_DATABASE_PATH=data/test_anveshq.db`
- scan/filtering values and source URLs
- SMTP settings for weekly email

## Run Commands

From `Backend/`:

- Daily scan:
```bash
python -m src.main
```

- Weekly universe build:
```bash
python -m src.master_builder
```

- Weekly email report:
```bash
python -m src.email_report
```

## Cleanup CLI

From `Backend/`:

- Cleanup momentum history:
```bash
python -m src.cleanup_service --cleanup-momentum
```

- Cleanup master JSON snapshots:
```bash
python -m src.cleanup_service --cleanup-master
```

- Validate stale/delisted companies:
```bash
python -m src.cleanup_service --validate-companies
```

- Cleanup old errors:
```bash
python -m src.cleanup_service --cleanup-errors
```

- Optimize SQLite DB:
```bash
python -m src.cleanup_service --optimize-db
```

- Run all cleanup operations:
```bash
python -m src.cleanup_service --full-cleanup
```

- Dry run (no deletion):
```bash
python -m src.cleanup_service --full-cleanup --dry-run
```

## GitHub Workflows

- `daily_scan.yml`
  - Runs daily at 12:30 UTC (6:00 PM IST)
  - Executes `src.main`
  - Commits `data/anveshq.db` only when changed

- `weekly_master_build.yml`
  - Runs Sunday 00:00 UTC (5:30 AM IST)
  - Executes `src.master_builder`
  - Commits `data/master/*.json`

- `weekly_email_report.yml`
  - Runs Sunday 16:30 UTC (10:00 PM IST)
  - Executes `src.email_report` (read-only DB usage)

- `monthly_validation.yml`
  - Runs first day of month at 00:00 UTC
  - Executes company validation + error cleanup + DB optimize
  - Commits DB when changed

## Backup and Restore

- Backup strategy: SQLite file is version-controlled in Git history.
- Restore procedure:
  1. Checkout a known-good commit containing `data/anveshq.db`.
  2. Copy that DB file forward.
  3. Re-run `python -m src.cleanup_service --optimize-db`.

## Troubleshooting

- `database is locked`
  - Commit retry is built in.
  - Re-run with fewer parallel tasks or after current job completes.

- DB size grows unexpectedly
  - Run:
    - `python -m src.cleanup_service --cleanup-momentum`
    - `python -m src.cleanup_service --cleanup-errors`
    - `python -m src.cleanup_service --optimize-db`
  - Investigate symbols not updated for long periods.

- Missing master universe file
  - Run `python -m src.master_builder` to regenerate `master-latest.json`.

- Email not sent
  - Verify `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `TO_EMAIL`.

## Testing

Run tests from repo root:

```bash
pytest Backend/tests -q
```

