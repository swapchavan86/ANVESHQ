# Anveshq · Fluxmind Backend

> **An automated Indian stock momentum intelligence engine.**
> Scans NSE/BSE daily, ranks momentum stocks, and delivers a curated weekly email report — all running on GitHub Actions with zero server cost.

---

## Table of Contents

- [What This Does](#what-this-does)
- [How It Works — Architecture](#how-it-works--architecture)
- [Project Layout](#project-layout)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Run Commands](#run-commands)
  - [Daily Scan](#daily-scan)
  - [Weekly Universe Build](#weekly-universe-build)
  - [Weekly Email Report](#weekly-email-report)
  - [Cleanup CLI](#cleanup-cli)
  - [Backtesting](#backtesting)
- [Backtesting — Full Guide](#backtesting--full-guide)
- [GitHub Actions Workflows](#github-actions-workflows)
- [SQLite & Encryption Notes](#sqlite--encryption-notes)
- [Data Retention Policies](#data-retention-policies)
- [Backup and Restore](#backup-and-restore)
- [Troubleshooting](#troubleshooting)
- [Testing](#testing)

---

## What This Does

Anveshq is a self-hosted stock research engine for Indian markets (NSE + BSE). It:

1. **Builds a universe** of all NSE/BSE equity stocks weekly from official sources
2. **Scans every trading day** for stocks showing momentum breakout signals using price, volume, and fundamental filters
3. **Ranks stocks** using a streak-based scoring system — the longer a stock keeps qualifying, the higher its rank
4. **Sends a weekly email** with the top picks, technical indicators, support/resistance levels, and a learning section
5. **Backtests the strategy** on historical data to measure actual signal performance (win rate, returns, Sharpe ratio)
6. **Cleans up stale data** monthly — validates delisted companies, compacts the database, and prunes old records

Everything runs automatically on **GitHub Actions at zero server cost**.

---

## How It Works — Architecture

```
                  +----------------------------------+
                  |  GitHub Actions Schedules        |
                  |  daily / weekly / monthly        |
                  +----------------+-----------------+
                                   |
          +------------------------+------------------------+
          |                        |                        |
          v                        v                        v
  +---------------+    +---------------------+    +------------------+
  | Weekly Rootset|    | Daily Fluxmind Scan |    | Weekly Email     |
  | master_builder|    | src.main            |    | src.email_report |
  +-------+-------+    +----------+----------+    +--------+---------+
          |                       |                        |
          v                       v                        v
  data/master/*.json      data/anveshq.db          reads DB → SMTP
  master-latest.json      (SQLCipher encrypted,
                           committed to repo)
```

### Momentum Scoring Logic

```
Stock passes filters?  ──No──> Skip
        │
        Yes
        │
        v
 Already in DB?  ──No──> Add with rank_score = 1
        │
        Yes
        │
        v
 Seen today already?  ──Yes──> Skip (idempotent)
        │
        No
        │
        v
 rank_score += 1  (capped at MAX_RANK)

 Not seen for 2 days?  ──> rank_score -= 1
 Not seen for 3 days?  ──> rank_score -= 2
 Not seen for >3 days? ──> rank_score = 0
```

### Daily Filters Applied to Each Stock

| Filter | Criterion |
|--------|-----------|
| Price | ≥ `MIN_PRICE` (default ₹20) |
| 52-Week High Proximity | Current price ≥ 90% of 52-week high |
| Relative Liquidity | 10D median turnover ≥ 60% of 180D median turnover |
| Volume Confirmation | 5D avg volume ≥ 1.25× 30D avg volume |
| Market Cap | ≥ `MIN_MCAP_CRORES` (default ₹1,000 Cr) |
| Debt/Equity | ≤ 3 (if available) |
| Trailing PE | Must not be negative (loss-making rejected) |
| Risk Score | ≤ 3 out of 7 (based on volatility, volume consistency, turnover) |

---

## Project Layout

```
Anveshq/
├── Backend/
│   ├── src/
│   │   ├── backtest.py          # Historical strategy backtester  ← NEW
│   │   ├── cleanup_service.py   # Data retention, DB optimisation
│   │   ├── config.py            # All settings via pydantic-settings
│   │   ├── database.py          # SQLAlchemy engine + SQLCipher setup
│   │   ├── email_report.py      # Weekly HTML email builder + SMTP sender
│   │   ├── main.py              # Fluxmind daily scan orchestrator
│   │   ├── master_builder.py    # Weekly universe (Rootset) builder
│   │   ├── models.py            # SQLAlchemy ORM models
│   │   ├── services.py          # Filters, ranking engine, parallel fetcher
│   │   ├── utils.py             # TickerLoader, Bhavcopy downloader
│   │   └── yahoo_finance.py     # yfinance wrappers with error handling
│   ├── templates/
│   │   ├── email_report.html    # HTML email template
│   │   └── anveshq_logo.png     # Optional email logo
│   ├── tests/
│   │   └── ...                  # pytest test suite
│   └── requirements.txt
├── data/
│   ├── anveshq.db               # Encrypted SQLite DB (tracked in git)
│   ├── backtest_results.csv     # Backtest output (generated, not tracked)
│   └── master/
│       ├── master-latest.json   # Current stock universe (tracked in git)
│       └── master-YYYY-MM-DD.json  # Weekly snapshots (last 7 kept)
├── .github/
│   └── workflows/
│       ├── daily_scan.yml
│       ├── weekly_master_build.yml
│       ├── weekly_email_report.yml
│       ├── monthly_validation.yml
│       └── cleanup_workflow_runs.yml
├── universe_cache.txt           # Daily ticker cache (not tracked)
└── README.md
```

---

## Prerequisites

- **Python 3.10+**
- **SQLCipher** system library (required for encrypted database)
- **Git**

### Install SQLCipher (by OS)

**Ubuntu / Debian / GitHub Actions:**
```bash
sudo apt-get update
sudo apt-get install -y build-essential libsqlcipher-dev
```

**macOS (Homebrew):**
```bash
brew install sqlcipher
```

**Windows:**
SQLCipher on Windows requires manual build or WSL. Recommended: use WSL2 with Ubuntu.

---

## Setup

### 1. Clone the repository
```bash
git clone https://github.com/your-username/anveshq.git
cd anveshq
```

### 2. Create and activate a virtual environment
```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies
```bash
cd Backend
pip install -r requirements.txt
```

### 4. Create your environment file
```bash
cp Backend/.env.example Backend/.env   # if example exists, else create manually
```

Edit `Backend/.env` with your settings (see [Environment Variables](#environment-variables) below).

### 5. Ensure data directories exist
```bash
mkdir -p data/master
```

### 6. Build the stock universe (first-time only)
```bash
cd Backend
python -m src.master_builder
```
This creates `data/master/master-latest.json` which the daily scanner needs.

### 7. Run the daily scan once to initialise the database
```bash
python -m src.main
```

---

## Environment Variables

Create `Backend/.env` with the following. All values can also be passed as GitHub Actions secrets.

```dotenv
# ── Core ──────────────────────────────────────────────
MODE=DEV                          # DEV | PROD | TEST
DATABASE_PATH=data/anveshq.db
TEST_DATABASE_PATH=data/test_anveshq.db
DB_PASSWORD=your-strong-password  # Required in DEV and PROD

# ── Universe Sources ──────────────────────────────────
USE_JSON_UNIVERSE=true
NSE_EQUITY_LIST_URL=https://archives.nseindia.com/content/equities/EQUITY_L.csv
NSE_NIFTY500_CSV_URL=https://archives.nseindia.com/content/indices/ind_nifty500list.csv
BSE_CM_CSV_URL=                   # Optional BSE source URL
BHAVCOPY_URL_TEMPLATE=https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip

# ── Scan Filters ──────────────────────────────────────
FUNDAMENTAL_CHECK_ENABLED=true
MIN_PRICE=20.0
MIN_MCAP_CRORES=1000.0
STREAK_THRESHOLD_DAYS=3
STOP_LOSS_PCT=-8.0
TAKE_PROFIT_PCT=15.0
NEAR_52_WEEK_HIGH_THRESHOLD=0.90
VOLUME_CONFIRMATION_FACTOR=1.25
RELATIVE_LIQUIDITY_FACTOR=0.6
REPETITION_COOLDOWN_DAYS=14
BREAKOUT_LOOKBACK_DAYS=20
MAX_RANK=100
DECAY_FACTOR=0.2
MARKET_REGIME_FILTER_ENABLED=true
MARKET_REGIME_INDEX=^NSEI
DIVERSIFICATION_ENABLED=true
MAX_STOCKS_PER_SECTOR=2
MAX_SMALL_CAP_TOP_PICKS=3

# ── Retention ─────────────────────────────────────────
DATA_RETENTION_WEEKS=104
CLEANUP_FREQUENCY_DAYS=7
MASTER_DATA_RETENTION_DAYS=7
ERROR_LOG_RETENTION_DAYS=90
STALE_SYMBOL_DAYS=30

# ── Email (for weekly report) ─────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_SSL=false
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your-app-password    # Gmail App Password, not account password
TO_EMAIL=recipient@example.com
```

> **Gmail setup:** Go to Google Account → Security → 2-Step Verification → App Passwords → generate one for "Mail".

---

## Run Commands

All commands are run from the `Backend/` directory.

### Daily Scan
```bash
python -m src.main
```
Scans all stocks in the universe, updates rankings in the database. Skips weekends and known holidays automatically.

---

### Weekly Universe Build
```bash
python -m src.master_builder
```
Fetches NSE + NIFTY 500 + BSE stock lists, creates `data/master/master-latest.json` and a timestamped snapshot.

---

### Weekly Email Report
```bash
python -m src.email_report
```
Reads top picks from the database, builds an HTML email with technical analysis, and sends it via SMTP. Requires email settings in `.env`.

---

### Cleanup CLI

```bash
# Delete old momentum records (older than DATA_RETENTION_WEEKS)
python -m src.cleanup_service --cleanup-momentum

# Delete old master JSON snapshots (keep last 7)
python -m src.cleanup_service --cleanup-master

# Validate stale/delisted companies against Yahoo Finance + Google
python -m src.cleanup_service --validate-companies

# Delete old error logs (older than ERROR_LOG_RETENTION_DAYS)
python -m src.cleanup_service --cleanup-errors

# Run VACUUM + ANALYZE to compact the SQLite database
python -m src.cleanup_service --optimize-db

# Run all of the above in one command
python -m src.cleanup_service --full-cleanup

# Dry run — shows what WOULD be deleted without actually deleting
python -m src.cleanup_service --full-cleanup --dry-run
```

---

## Backtesting

### What the backtester does

`src/backtest.py` replays the full momentum strategy on historical data without lookahead bias:

1. Downloads price history for all tickers in the universe for the requested date range
2. For each trading day, runs **only the data available up to that day** through all momentum filters (price, volume, liquidity, risk score)
3. Simulates the same rank-increment / rank-decay logic as the live scanner
4. Selects top picks using the same repetition-control logic
5. Measures actual price returns at **5, 10, and 20 trading days** after each signal
6. Calculates win rate, average returns, maximum drawdown, and an approximate Sharpe ratio
7. Saves every trade row + a summary row to a CSV file

### Backtesting Commands

**Basic run — last 1 year:**
```bash
python -m src.backtest --start 2024-01-01 --end 2024-12-31
```

**Specific date range with output path:**
```bash
python -m src.backtest \
  --start 2023-01-01 \
  --end 2024-12-31 \
  --output data/backtest_2023_2024.csv
```

**Test on a small set of symbols first (fast, good for debugging):**
```bash
python -m src.backtest \
  --start 2024-06-01 \
  --end 2024-12-31 \
  --symbols RELIANCE.NS,TCS.NS,INFY.NS,HDFCBANK.NS,ICICIBANK.NS
```

**With fundamentals check enabled (slower, more accurate):**
```bash
python -m src.backtest \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --use-current-fundamentals
```

**All options:**
```bash
python -m src.backtest --help
```

**Walk-forward optimization from a backtest CSV:**
```bash
python -m src.optimize \
  --csv data/backtest_results.csv \
  --output optimization_results.json
```

Use the best out-of-sample values from `optimization_results.json` to tune `.env` settings such as `NEAR_52_WEEK_HIGH_THRESHOLD`, `VOLUME_CONFIRMATION_FACTOR`, `MAX_RANK`, and the risk/stop controls.

| Option | Default | Description |
|--------|---------|-------------|
| `--start` | *(required)* | Backtest start date `YYYY-MM-DD` |
| `--end` | *(required)* | Backtest end date `YYYY-MM-DD` |
| `--output` | `data/backtest_results.csv` | CSV output path |
| `--max-workers` | `8` | Parallel download threads |
| `--timeout` | `15` | yfinance request timeout (seconds) |
| `--lookback-days` | `370` | Calendar days of history used per signal date (≈1 year) |
| `--symbols` | *(full universe)* | Comma-separated symbols for a subset run |
| `--use-current-fundamentals` | `false` | Apply PE/debt/mcap filter using current data |

### Backtest Output (CSV)

The CSV contains two types of rows:

**TRADE rows** — one per stock signal:

| Column | Description |
|--------|-------------|
| `row_type` | `TRADE` |
| `signal_date` | Date the stock qualified |
| `symbol` | Stock ticker (e.g. `RELIANCE.NS`) |
| `entry_close` | Closing price on signal date |
| `rank_score` | Rank at time of signal |
| `daily_rank_delta` | Rank increase that day |
| `risk_score` | Risk score (0–7, lower is better) |
| `close_5d` / `close_10d` / `close_20d` | Actual close prices at each horizon |
| `return_5d_pct` / `return_10d_pct` / `return_20d_pct` | Return % at each horizon |

**SUMMARY row** — one row at the bottom:

| Column | Description |
|--------|-------------|
| `row_type` | `SUMMARY` |
| `trade_count` | Total number of signal trades |
| `win_rate_10d_pct` | % of trades profitable at 10-day mark |
| `average_return_5d_pct` | Mean return at 5 trading days |
| `average_return_10d_pct` | Mean return at 10 trading days |
| `average_return_20d_pct` | Mean return at 20 trading days |
| `maximum_drawdown_pct` | Worst peak-to-trough decline across all trades |
| `sharpe_ratio_approx` | Annualised Sharpe ratio approximation |

### Important Caveats

- **Fundamental data** — yfinance only provides *current* fundamentals, not historical ones. Using `--use-current-fundamentals` introduces mild lookahead bias for that filter. Without the flag, fundamentals are treated as pass (more optimistic results).
- **Survivorship bias** — delisted stocks that no longer appear in Yahoo Finance are excluded. Results may be slightly optimistic.
- **Slippage and costs** — not modelled. Real-world returns will be lower due to brokerage, STT, impact cost.
- **Data gaps** — yfinance occasionally returns incomplete data. The backtester skips symbols with fewer than `MIN_HISTORY_DAYS` rows.

---

## GitHub Actions Workflows

| Workflow | Schedule | What it runs |
|----------|----------|--------------|
| `daily_scan.yml` | Daily 12:30 UTC (6:00 PM IST) | `src.main` — full momentum scan, commits DB if changed |
| `weekly_master_build.yml` | Sunday 00:00 UTC (5:30 AM IST) | `src.master_builder` — rebuilds stock universe JSON |
| `weekly_email_report.yml` | Sunday 16:30 UTC (10:00 PM IST) | `src.email_report` — sends the weekly email |
| `monthly_validation.yml` | 1st of month 00:00 UTC | Company validation + error cleanup + DB optimize, commits DB if changed |
| `cleanup_workflow_runs.yml` | Daily 01:30 UTC | Deletes GitHub Actions run history older than 7 days |

All workflows can also be triggered manually via **Actions → Run workflow** in GitHub.

### Required GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Required by | Description |
|--------|-------------|-------------|
| `DB_PASSWORD` | All scan/cleanup workflows | SQLCipher encryption key for `anveshq.db` |
| `SMTP_USER` | `weekly_email_report.yml` | Gmail address |
| `SMTP_PASSWORD` | `weekly_email_report.yml` | Gmail App Password |
| `TO_EMAIL` | `weekly_email_report.yml` | Recipient email address |
| `BHAVCOPY_URL_TEMPLATE` | `daily_scan.yml` | NSE Bhavcopy URL template with `{YYYYMMDD}` placeholder |
| `NSE_EQUITY_LIST_URL` | All scan workflows | NSE equity master CSV URL |
| `NSE_NIFTY500_CSV_URL` | All scan workflows | NIFTY 500 CSV URL |
| `MODE` | All workflows | `PROD` for production runs |

Optional secrets (have defaults in `config.py`):
`MIN_PRICE`, `MIN_MCAP_CRORES`, `STREAK_THRESHOLD_DAYS`, `STOP_LOSS_PCT`, `TAKE_PROFIT_PCT`, `NEAR_52_WEEK_HIGH_THRESHOLD`, `VOLUME_CONFIRMATION_FACTOR`, `RELATIVE_LIQUIDITY_FACTOR`, `REPETITION_COOLDOWN_DAYS`, `BREAKOUT_LOOKBACK_DAYS`, `MAX_RANK`, `DECAY_FACTOR`, `FUNDAMENTAL_CHECK_ENABLED`, `MARKET_REGIME_FILTER_ENABLED`, `MARKET_REGIME_INDEX`, `DIVERSIFICATION_ENABLED`, `MAX_STOCKS_PER_SECTOR`, `MAX_SMALL_CAP_TOP_PICKS`

---

## SQLite & Encryption Notes

- **Production DB**: `data/anveshq.db` — encrypted with SQLCipher (AES-256), committed to the repo
- **Test DB**: `data/test_anveshq.db` — plaintext, gitignored
- **First run behaviour**: if an existing *plaintext* `data/anveshq.db` is found, it is migrated in-place to encrypted format automatically
- **DEV mode recovery**: if `DB_PASSWORD` does not match the existing DB, the old DB is backed up with a timestamp suffix and a fresh DB is created
- **WAL mode** is enabled on every connection for better concurrency

SQLite PRAGMAs applied on connect:
```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-10000;
PRAGMA foreign_keys=ON;
PRAGMA temp_store=MEMORY;
```

---

## Data Retention Policies

| Data | Retention |
|------|-----------|
| `momentum_ranks` table | 104 weeks (2 years) |
| `errors` table | 90 days |
| `data/master/` snapshots | Last 7 daily snapshots + `master-latest.json` |
| `users`, `verification_codes` | Retained permanently |
| `backtest_results.csv` | Not auto-cleaned; manage manually |

Cleanup runs `VACUUM` + `ANALYZE` after deletions to keep the DB compact.

---

## Backup and Restore

**Backup strategy:** `data/anveshq.db` is version-controlled. Every daily scan commits it to Git if changed, so your Git history *is* your backup.

**Restore procedure:**
```bash
# 1. Find a known-good commit
git log --oneline -- data/anveshq.db

# 2. Checkout just the DB file from that commit
git checkout <commit-hash> -- data/anveshq.db

# 3. Compact it
cd Backend
python -m src.cleanup_service --optimize-db
```

---

## Troubleshooting

**`database is locked`**
Commit retry is built-in (3 attempts by default). If it persists, re-run after the current job completes, or reduce `--max-workers`.

**DB size growing unexpectedly**
```bash
python -m src.cleanup_service --cleanup-momentum
python -m src.cleanup_service --cleanup-errors
python -m src.cleanup_service --optimize-db
```

**Missing master universe file**
```bash
python -m src.master_builder
```

**Email not sent**
- Verify all SMTP settings in `.env`
- For Gmail, ensure you're using an **App Password** (not your account password) and have 2FA enabled
- Check that `SMTP_HOST` is not set to `localhost`

**Backtest runs but produces no TRADE rows**
- The filters are strict. Try a shorter period first with `--symbols` to debug
- Check that `data/master/master-latest.json` exists and has records
- Try without `--use-current-fundamentals` to isolate the issue

**yfinance `401 Unauthorized` or rate limit errors**
These are handled gracefully — the scanner falls back to Bhavcopy data or skips the symbol. No action needed, but results may be incomplete for those symbols.

**GitHub Actions workflow fails with `SQLite DB file not found`**
This is a safe exit — it means the scan ran but no stocks qualified (e.g. market was closed). Check the step logs for the actual reason.

---

## Testing

Run from the repository root:

```bash
pytest Backend/tests -q
```

For a specific test file:
```bash
pytest Backend/tests/test_services.py -v
```

---

## Disclaimer

This project is for **educational and research purposes only**. It is not investment advice. Anveshq is not a SEBI-registered investment advisor. Always do your own research and consult a qualified financial advisor before making investment decisions. Past performance of any screened signals does not guarantee future results.
