import logging
import os
import time
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from src.config import get_settings

logger = logging.getLogger("Anveshq.Database")

_engine = None
_SessionLocal = None


def _is_sqlite_locked_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _is_sqlite_statements_in_progress_error(exc: Exception) -> bool:
    return "sql statements in progress" in str(exc).lower()


def _ensure_parent_directory(file_path: str) -> None:
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _initialize_db_components() -> None:
    global _engine, _SessionLocal
    if _engine is not None and _SessionLocal is not None:
        return

    settings = get_settings()
    db_path = settings.active_database_file_path
    _ensure_parent_directory(db_path)

    _engine = create_engine(
        settings.active_database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=QueuePool,
        pool_size=20,
        max_overflow=40,
        pool_timeout=30,
        pool_pre_ping=True,
    )

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-10000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def reset_db_components() -> None:
    """Reset DB globals (used by tests when environment variables change)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_engine():
    _initialize_db_components()
    return _engine


def get_session_local():
    _initialize_db_components()
    return _SessionLocal


@contextmanager
def get_db_context():
    """Context manager for DB sessions with retry on SQLite lock during commit."""
    settings = get_settings()
    session_local = get_session_local()
    session: Session = session_local()
    max_attempts = max(1, int(settings.DB_LOCK_RETRY_COUNT))
    retry_delay = max(0.0, float(settings.DB_LOCK_RETRY_DELAY_SECONDS))
    try:
        yield session
        for attempt in range(1, max_attempts + 1):
            try:
                session.commit()
                break
            except OperationalError as exc:
                session.rollback()
                retryable = _is_sqlite_locked_error(exc) or _is_sqlite_statements_in_progress_error(exc)
                if retryable and attempt < max_attempts:
                    logger.warning(
                        "SQLite commit retry due to transient error. Retry %s/%s in %.2fs. Error=%s",
                        attempt,
                        max_attempts,
                        retry_delay,
                        exc,
                    )
                    time.sleep(retry_delay)
                    continue
                raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_wal_checkpoint(mode: str = "TRUNCATE") -> None:
    """Checkpoint WAL to keep committed data in the main SQLite file."""
    with get_engine().connect() as connection:
        connection.exec_driver_sql(f"PRAGMA wal_checkpoint({mode})")


def vacuum_database() -> None:
    """Run VACUUM to reclaim disk space."""
    with get_engine().connect() as connection:
        connection.exec_driver_sql("VACUUM")


def analyze_database() -> None:
    """Run ANALYZE to refresh SQLite query planner statistics."""
    with get_engine().connect() as connection:
        connection.exec_driver_sql("ANALYZE")


def get_database_size(db_file_path: str | None = None) -> float:
    """Return database size in MB."""
    settings = get_settings()
    file_path = db_file_path or settings.active_database_file_path
    if not os.path.exists(file_path):
        return 0.0
    bytes_size = os.path.getsize(file_path)
    return round(bytes_size / (1024 * 1024), 3)


def execute_sql(sql: str) -> None:
    """Execute raw SQL against current engine."""
    with get_engine().connect() as connection:
        connection.execute(text(sql))
