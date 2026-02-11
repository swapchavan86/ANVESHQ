import datetime
import logging
import os
import sys
import zoneinfo

# Add project root to path to support `python -m src.main`.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import src.cleanup_service as cleanup_service
from src.config import get_settings
from src.database import get_database_size, get_engine, run_wal_checkpoint
from src.models import Base
from src.services import ErrorLogger, MarketValidator, StockFetcher
from src.utils import TickerLoader
from src.database import get_db_context

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="[ANVESHQ:FLUXMIND] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("Anveshq")


def populate_known_errors() -> None:
    known_errors = [
        "The truth value of a DataFrame is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all().",
        "No objects to concatenate",
        "dictionary changed size during iteration",
    ]
    with get_db_context() as session:
        for error_message in known_errors:
            ErrorLogger.log_error(session, error_message)


def bootstrap_db() -> None:
    Base.metadata.create_all(bind=get_engine())
    populate_known_errors()


def _ensure_data_directory() -> None:
    os.makedirs("data", exist_ok=True)
    os.makedirs(os.path.dirname(settings.active_database_file_path), exist_ok=True)


def _log_database_size(prefix: str) -> None:
    db_size_mb = get_database_size()
    logger.info("%s database size: %.3f MB", prefix, db_size_mb)
    if db_size_mb > settings.DB_SIZE_WARNING_MB:
        logger.warning(
            "Database size %.3f MB crossed warning threshold %.3f MB.",
            db_size_mb,
            settings.DB_SIZE_WARNING_MB,
        )


def _run_periodic_cleanup(today: datetime.date) -> None:
    if cleanup_service.is_cleanup_due(
        cleanup_service.METADATA_LAST_MOMENTUM_CLEANUP,
        settings.CLEANUP_FREQUENCY_DAYS,
    ):
        logger.info("Cleanup day reached. Running momentum cleanup.")
        stats = cleanup_service.cleanup_old_momentum_records(dry_run=False)
        cleanup_service.set_metadata_date(cleanup_service.METADATA_LAST_MOMENTUM_CLEANUP, today)
        logger.info("Momentum cleanup stats: %s", stats.to_dict())
    else:
        logger.info("Momentum cleanup skipped (not due yet).")


def main() -> None:
    logger.info("--- Starting Fluxmind Engine ---")
    logger.info("--- Running in %s mode ---", settings.MODE)
    logger.info("--- Active DB path: %s ---", settings.active_database_file_path)

    _ensure_data_directory()

    if not MarketValidator.should_run(settings):
        sys.exit(0)

    bootstrap_db()
    _log_database_size("Before scan")

    tickers = TickerLoader.get_unique_tickers()
    if not tickers:
        logger.critical("No tickers found.")
        sys.exit(1)

    StockFetcher.scan_stocks_parallel(tickers, batch_size=50, max_workers=10)

    with get_db_context() as session:
        today = datetime.datetime.now(zoneinfo.ZoneInfo(settings.TIMEZONE)).date()
        top_movers = StockFetcher.get_top_movers_with_repetition_control(session, settings, today)
        logger.info("Top movers selected after repetition control: %s", len(top_movers))

    duplicate_removed = cleanup_service.cleanup_duplicate_symbols(dry_run=False)
    if duplicate_removed:
        logger.info("Duplicate symbol cleanup removed %s stale rows.", duplicate_removed)

    _run_periodic_cleanup(today=today)
    run_wal_checkpoint(mode="TRUNCATE")
    _log_database_size("After scan/cleanup")
    logger.info("--- Fluxmind Engine Run Completed Successfully ---")
    os._exit(0)


if __name__ == "__main__":
    main()
