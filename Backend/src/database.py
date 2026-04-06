import logging
import os
import sqlite3
import time
from datetime import datetime
from contextlib import contextmanager
import gc
import shutil
from types import ModuleType

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from src.config import get_settings

logger = logging.getLogger("Anveshq.Database")

_engine = None
_SessionLocal = None


def _load_sqlcipher_dbapi() -> ModuleType | None:
    try:
        import sqlcipher3.dbapi2 as sqlcipher_dbapi

        return sqlcipher_dbapi
    except ModuleNotFoundError:
        pass

    try:
        import pysqlcipher3.dbapi2 as sqlcipher_dbapi

        return sqlcipher_dbapi
    except ModuleNotFoundError:
        return None


def _is_sqlite_locked_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _is_sqlite_statements_in_progress_error(exc: Exception) -> bool:
    return "sql statements in progress" in str(exc).lower()


def _ensure_parent_directory(file_path: str) -> None:
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@contextmanager
def _suppress_native_stderr():
    """Temporarily silence native stderr output from SQLCipher key probes."""
    devnull_fd = None
    stderr_fd_copy = None
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        stderr_fd_copy = os.dup(2)
        os.dup2(devnull_fd, 2)
        yield
    finally:
        if stderr_fd_copy is not None:
            os.dup2(stderr_fd_copy, 2)
            os.close(stderr_fd_copy)
        if devnull_fd is not None:
            os.close(devnull_fd)


def _ensure_password_configuration(settings) -> None:
    if settings.MODE != "TEST" and not settings.DB_PASSWORD:
        raise RuntimeError(
            "DB_PASSWORD is required when MODE is not TEST. "
            "Set DB_PASSWORD in Backend/.env or GitHub Actions secrets."
        )


def _ensure_sqlcipher_dependency(settings) -> None:
    if not settings.DB_PASSWORD:
        return
    if _load_sqlcipher_dbapi() is None:
        raise RuntimeError(
            "DB_PASSWORD is set, but SQLCipher DBAPI is missing. "
            "Install `sqlcipher3` (or `pysqlcipher3`) before starting the app."
        )


def _is_plaintext_sqlite_database(file_path: str) -> bool:
    if not os.path.exists(file_path):
        return False
    connection = None
    try:
        connection = sqlite3.connect(file_path, timeout=5)
        cursor = connection.cursor()
        cursor.execute("SELECT count(*) FROM sqlite_master")
        cursor.fetchone()
        cursor.close()
        return True
    except sqlite3.DatabaseError:
        return False
    finally:
        if connection is not None:
            connection.close()


def _cleanup_sqlite_sidecar_files(file_path: str) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar_file = f"{file_path}{suffix}"
        if os.path.exists(sidecar_file):
            os.remove(sidecar_file)


def _backup_database_with_sidecars(file_path: str, suffix: str) -> str | None:
    if not os.path.exists(file_path):
        return None

    backup_file = f"{file_path}.{suffix}"
    try:
        _replace_file_with_retry(file_path, backup_file, retries=20, delay_seconds=0.25)
    except PermissionError:
        shutil.copy2(file_path, backup_file)
        os.remove(file_path)

    for sidecar_suffix in ("-wal", "-shm"):
        sidecar_file = f"{file_path}{sidecar_suffix}"
        if os.path.exists(sidecar_file):
            backup_sidecar = f"{backup_file}{sidecar_suffix}"
            try:
                _replace_file_with_retry(
                    sidecar_file,
                    backup_sidecar,
                    retries=20,
                    delay_seconds=0.25,
                )
            except PermissionError:
                shutil.copy2(sidecar_file, backup_sidecar)
                os.remove(sidecar_file)

    return backup_file


def _replace_file_with_retry(source_file: str, target_file: str, retries: int = 5, delay_seconds: float = 0.2) -> None:
    last_error: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            os.replace(source_file, target_file)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(max(0.0, delay_seconds))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to replace database file {target_file}.")


def _migrate_plaintext_to_sqlcipher(file_path: str, password: str) -> None:
    sqlcipher_dbapi = _load_sqlcipher_dbapi()
    if sqlcipher_dbapi is None:
        raise RuntimeError("SQLCipher DBAPI is required for database encryption migration.")

    temp_encrypted_file = f"{file_path}.enc_tmp"
    if os.path.exists(temp_encrypted_file):
        os.remove(temp_encrypted_file)

    sqlcipher_connection = None
    try:
        sqlcipher_connection = sqlcipher_dbapi.connect(file_path)
        cursor = sqlcipher_connection.cursor()
        cursor.execute(
            f"ATTACH DATABASE {_sql_literal(temp_encrypted_file)} "
            f"AS encrypted KEY {_sql_literal(password)}"
        )
        cursor.execute("SELECT sqlcipher_export('encrypted')")
        cursor.execute("DETACH DATABASE encrypted")
        sqlcipher_connection.commit()
        cursor.close()
    except Exception as exc:
        if os.path.exists(temp_encrypted_file):
            os.remove(temp_encrypted_file)
        raise RuntimeError(f"Failed to encrypt existing SQLite database at {file_path}.") from exc
    finally:
        if sqlcipher_connection is not None:
            sqlcipher_connection.close()

    gc.collect()
    _replace_file_with_retry(temp_encrypted_file, file_path, retries=20, delay_seconds=0.25)
    _cleanup_sqlite_sidecar_files(file_path)


def _can_open_sqlcipher_database(file_path: str, password: str) -> bool:
    if not os.path.exists(file_path):
        return True

    sqlcipher_dbapi = _load_sqlcipher_dbapi()
    if sqlcipher_dbapi is None:
        return False

    connection = None
    try:
        with _suppress_native_stderr():
            connection = sqlcipher_dbapi.connect(file_path)
            cursor = connection.cursor()
            cursor.execute(f"PRAGMA key={_sql_literal(password)}")
            cursor.execute("SELECT count(*) FROM sqlite_master")
            cursor.fetchone()
            cursor.close()
        return True
    except Exception:
        return False
    finally:
        if connection is not None:
            connection.close()


def _handle_unreadable_encrypted_database(settings, db_path: str) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_suffix = f"invalid_key_backup_{timestamp}"
    backup_file = _backup_database_with_sidecars(db_path, backup_suffix)
    logger.warning(
        "DEV recovery: existing encrypted DB could not be opened with the configured DB_PASSWORD. "
        "Backed it up to %s and creating a fresh database at %s.",
        backup_file,
        db_path,
    )


def _prepare_database_file(settings, db_path: str) -> None:
    _ensure_password_configuration(settings)
    _ensure_sqlcipher_dependency(settings)
    if not settings.DB_PASSWORD:
        return
    if _is_plaintext_sqlite_database(db_path):
        logger.warning("Detected plaintext SQLite DB. Encrypting file with SQLCipher at %s", db_path)
        _migrate_plaintext_to_sqlcipher(db_path, settings.DB_PASSWORD)
        logger.info("SQLite DB encryption completed at %s", db_path)
        return

    if not _can_open_sqlcipher_database(db_path, settings.DB_PASSWORD):
        if settings.MODE == "DEV":
            _handle_unreadable_encrypted_database(settings, db_path)
            return
        raise RuntimeError(
            "Database authentication failed before engine startup. "
            "Verify DB_PASSWORD matches the encrypted database."
        )


def _validate_database_access() -> None:
    try:
        with _engine.connect() as connection:
            connection.exec_driver_sql("SELECT count(*) FROM sqlite_master")
    except Exception as exc:
        raise RuntimeError(
            "Database authentication failed. Verify DB_PASSWORD and SQLCipher configuration."
        ) from exc


def _create_engine_instance(settings):
    return create_engine(
        settings.active_database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=QueuePool,
        pool_size=20,
        max_overflow=40,
        pool_timeout=30,
        pool_pre_ping=True,
    )


def _configure_engine(engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-10000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()


def _recover_dev_database_from_auth_failure(settings, db_path: str, exc: RuntimeError) -> bool:
    if settings.MODE != "DEV" or not settings.DB_PASSWORD or not os.path.exists(db_path):
        return False

    global _engine, _SessionLocal

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_suffix = f"invalid_key_backup_{timestamp}"

    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None

    backup_file = _backup_database_with_sidecars(db_path, backup_suffix)
    logger.warning(
        "DEV recovery: existing encrypted DB could not be opened with the configured DB_PASSWORD. "
        "Backed it up to %s and creating a fresh database at %s. Original error: %s",
        backup_file,
        db_path,
        exc,
    )
    return True


def _initialize_db_components() -> None:
    global _engine, _SessionLocal
    if _engine is not None and _SessionLocal is not None:
        return

    settings = get_settings()
    db_path = settings.active_database_file_path
    _ensure_parent_directory(db_path)
    _prepare_database_file(settings, db_path)

    _engine = _create_engine_instance(settings)
    _configure_engine(_engine)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    try:
        _validate_database_access()
    except RuntimeError as exc:
        if not _recover_dev_database_from_auth_failure(settings, db_path, exc):
            raise
        _engine = _create_engine_instance(settings)
        _configure_engine(_engine)
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        _validate_database_access()


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
