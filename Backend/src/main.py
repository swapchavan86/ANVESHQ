import sys
import os
import logging

# HACK: Add the root of the project to the path
# to allow for relative imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_engine, get_db_context
from src.models import Base
from src.config import get_settings
from src.services import MarketValidator, StockFetcher, ErrorLogger
from src.utils import TickerLoader

logging.basicConfig(
    level=getattr(logging, get_settings().LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("MomentumService")

def populate_known_errors():
    known_errors = [
        "The truth value of a DataFrame is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all().",
        "No objects to concatenate",
        "dictionary changed size during iteration"
    ]
    with get_db_context() as session:
        for error_message in known_errors:
            ErrorLogger.log_error(session, error_message)

def bootstrap_db():
    Base.metadata.create_all(bind=get_engine())
    populate_known_errors()

def main():
    logger.info("--- Starting Real-Time Momentum Scanner (Parallel) ---")
    
    current_settings = get_settings()
    logger.info(f"--- Running in {current_settings.MODE} mode ---")
    if current_settings.MODE == "PROD" or current_settings.MODE == "DEV":
        logger.info(f"--- Connecting to DB: {current_settings.DATABASE_URL.split('@')[-1]} ---")
    else:
        logger.info(f"--- Connecting to DB: {current_settings.TEST_DATABASE_URL} ---")
    
    if not MarketValidator.should_run(current_settings):
        sys.exit(0)

    bootstrap_db()

    # 1. Load Tickers
    tickers = TickerLoader.get_unique_tickers()
    if not tickers:
        logger.critical("No tickers found.")
        sys.exit(1)

    # 2. Start Parallel Scanning
    # 11,000 stocks / 50 batch size = 220 batches.
    # 10 workers running concurrently = very fast.
    StockFetcher.scan_stocks_parallel(tickers, batch_size=50, max_workers=10)
            
    logger.info("--- Job Completed Successfully ---")
    os._exit(0)

if __name__ == "__main__":
    main()
