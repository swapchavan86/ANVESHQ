import datetime as dt
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.cleanup_service import cleanup_error_logs, cleanup_old_master_files, cleanup_old_momentum_records
from src.config import get_settings
from src.database import get_db_context, get_engine, reset_db_components, _load_sqlcipher_dbapi
from src.models import Base, Error, MomentumStock


@pytest.fixture
def configured_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_anveshq.db"
    master_dir = tmp_path / "master"
    master_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("MODE", "TEST")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("TEST_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DB_PASSWORD", "")
    monkeypatch.setenv("MASTER_DATA_DIRECTORY", str(master_dir))
    monkeypatch.setenv("JSON_UNIVERSE_PATH", str(master_dir / "master-latest.json"))
    monkeypatch.setenv("DATA_RETENTION_WEEKS", "1")
    monkeypatch.setenv("ERROR_LOG_RETENTION_DAYS", "30")
    monkeypatch.setenv("MASTER_DATA_RETENTION_DAYS", "2")
    monkeypatch.setenv("CLEANUP_BATCH_SIZE", "2")

    get_settings.cache_clear()
    reset_db_components()
    Base.metadata.create_all(bind=get_engine())
    yield {"db_path": db_path, "master_dir": master_dir}
    reset_db_components()
    get_settings.cache_clear()


def test_cleanup_old_momentum_records_removes_stale_rows(configured_environment):
    today = dt.date.today()
    with get_db_context() as session:
        session.add_all(
            [
                MomentumStock(
                    symbol="OLD.NS",
                    last_seen_date=today - dt.timedelta(days=20),
                    rank_score=4,
                    daily_rank_delta=1,
                    current_price=120.0,
                ),
                MomentumStock(
                    symbol="FRESH.NS",
                    last_seen_date=today - dt.timedelta(days=2),
                    rank_score=7,
                    daily_rank_delta=1,
                    current_price=250.0,
                ),
            ]
        )

    stats = cleanup_old_momentum_records(dry_run=False)
    assert stats.deleted_count == 1

    with get_db_context() as session:
        remaining = session.execute(select(MomentumStock.symbol)).scalars().all()
    assert remaining == ["FRESH.NS"]


def test_cleanup_error_logs_removes_old_entries(configured_environment):
    now = dt.datetime.now()
    with get_db_context() as session:
        session.add_all(
            [
                Error(
                    error_code="old_error",
                    error_message="Old entry",
                    error_details={},
                    timestamp=now - dt.timedelta(days=45),
                ),
                Error(
                    error_code="new_error",
                    error_message="New entry",
                    error_details={},
                    timestamp=now - dt.timedelta(days=5),
                ),
            ]
        )

    stats = cleanup_error_logs(dry_run=False)
    assert stats.deleted_count == 1

    with get_db_context() as session:
        remaining_codes = session.execute(select(Error.error_code)).scalars().all()
    assert remaining_codes == ["new_error"]


def test_cleanup_old_master_files_keeps_latest_and_recent(configured_environment):
    master_dir = configured_environment["master_dir"]
    today = dt.date.today()

    latest = master_dir / "master-latest.json"
    latest.write_text("{}", encoding="utf-8")
    for offset in range(5):
        snapshot = master_dir / f"master-{(today - dt.timedelta(days=offset)).isoformat()}.json"
        snapshot.write_text("{}", encoding="utf-8")

    stats = cleanup_old_master_files(dry_run=False)

    assert len(stats.deleted_files) == 3
    assert "master-latest.json" in stats.kept_files
    assert latest.exists()
    remaining_snapshots = sorted(path.name for path in master_dir.glob("master-*.json"))
    assert len(remaining_snapshots) == 3  # latest + 2 snapshot files


def test_dev_mode_recovers_from_invalid_sqlcipher_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sqlcipher_dbapi = _load_sqlcipher_dbapi()
    if sqlcipher_dbapi is None:
        pytest.skip("SQLCipher DBAPI is not installed")

    db_path = tmp_path / "dev_encrypted.db"
    master_dir = tmp_path / "master"
    master_dir.mkdir(parents=True, exist_ok=True)

    connection = sqlcipher_dbapi.connect(str(db_path))
    cursor = connection.cursor()
    cursor.execute("PRAGMA key='correct-password'")
    cursor.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
    connection.commit()
    cursor.close()
    connection.close()

    monkeypatch.setenv("MODE", "DEV")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("TEST_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DB_PASSWORD", "wrong-password")
    monkeypatch.setenv("MASTER_DATA_DIRECTORY", str(master_dir))
    monkeypatch.setenv("JSON_UNIVERSE_PATH", str(master_dir / "master-latest.json"))

    get_settings.cache_clear()
    reset_db_components()

    Base.metadata.create_all(bind=get_engine())

    backup_files = list(tmp_path.glob("dev_encrypted.db.invalid_key_backup_*"))
    assert len(backup_files) == 1
    assert db_path.exists()

    reset_db_components()
    get_settings.cache_clear()
