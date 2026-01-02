import logging
import datetime
import zoneinfo
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config import get_settings # Keep import for use within functions
from src.models import MomentumStock, Error
from src.database import get_db_context
import secrets
import string
import time

logger = logging.getLogger("MomentumService")
logger.setLevel(logging.INFO)
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# --- CLASS 1: QUALITY & FRAUD CHECKS ---
class FraudDetector:
    @staticmethod
    def basic_liquidity_check(df: pd.DataFrame, current_price: float) -> bool:
        """
        Stage 1 Check:
        Turnover > 50 Lakhs (0.5 Cr).
        
        Why? 
        If Price is 100, we need only 50,000 Volume (Easy for genuine small caps).
        This allows Affordable stocks to pass through.
        """
        
        if df.empty or len(df) < 10: return False
        avg_volume_10d = df['Volume'].tail(10).mean()
        avg_turnover = avg_volume_10d * current_price
        if avg_turnover < 5_000_000:
            return False
        return True

    @staticmethod
    def deep_fundamental_check(symbol: str, settings_obj) -> bool: # Added settings_obj
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.get('info', {}) # Use .get to avoid KeyError
            
            # 1. Market Cap Check (Now > 100 Cr via Config)
            mcap = info.get('marketCap', 0)
            if mcap is not None and mcap < (settings_obj.MIN_MCAP_CRORES * 10_000_000):
                logger.info(f"❌ REJECT {symbol}: Mcap too low ({mcap})")
                return False

            # 2. Loss Making Check
            # We reject Negative PE (Loss making), BUT we allow High PE.
            # Growth stocks often have PE > 50 or 80. That is allowed.
            pe = info.get('trailingPE')
            if pe is not None and pe < 0:
                 logger.info(f"❌ REJECT {symbol}: Loss Making (Negative PE)")
                 return False
            
            # 3. Solvency Check
            # Debt/Equity > 3 is still risky for retail.
            dte = info.get('debtToEquity')
            if dte is not None and dte > 300:
                logger.info(f"❌ REJECT {symbol}: High Debt (D/E > 3)")
                return False

            return True
        except Exception as e:
            logger.warning(f"⚠️ Could not verify fundamentals for {symbol}: {e}")
            with get_db_context() as session:
                ErrorLogger.log_error(session, str(e))
            return True 

# --- CLASS 2: DB MANAGEMENT ---
class RankingEngine:
    def __init__(self, session: Session, settings_obj): # Added settings_obj
        self.session = session
        self.settings = settings_obj
        self.today = datetime.datetime.now(zoneinfo.ZoneInfo(self.settings.TIMEZONE)).date()

    def update_ranking(self, symbol: str, price: float, low_52: float, high_date: datetime.date):
        stmt = select(MomentumStock).where(MomentumStock.symbol == symbol)
        stock = self.session.execute(stmt).scalar_one_or_none()

        if stock:
            delta_days = (self.today - stock.last_seen_date).days
            stock.current_price = price
            stock.low_52_week = low_52
            stock.high_52_week_date = high_date
            
            if delta_days == 0: return

            if delta_days <= self.settings.STREAK_THRESHOLD_DAYS: # Use self.settings
                stock.rank_score += 1
            else:
                stock.rank_score = 1
            
            stock.last_seen_date = self.today
        else:
            new_stock = MomentumStock(
                symbol=symbol,
                rank_score=1,
                last_seen_date=self.today,
                current_price=price,
                low_52_week=low_52,
                high_52_week_date=high_date
            )
            self.session.add(new_stock)
            logger.info(f"✅ QUALIFIED & SAVED: {symbol} | Price: {price}")
        
        try:
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            with get_db_context() as session:
                ErrorLogger.log_error(session, str(e))


# --- CLASS 3: PARALLEL FETCHER ---
class StockFetcher:
    @staticmethod
    def process_single_batch(batch_tickers: list[str], batch_id: int, settings_obj) -> None: # Added settings_obj
        logger.info(f"--- Starting Batch {batch_id} ---")
        for i in range(3): # Retry up to 3 times
            try:
                data = yf.download(batch_tickers, period="1y", group_by='ticker', threads=False, progress=False, auto_adjust=True)
                break # If successful, break the loop
            except RuntimeError as e:
                if "dictionary changed size during iteration" in str(e):
                    logger.warning(f"Batch {batch_id} failed with RuntimeError, retrying... ({i+1}/3)")
                    time.sleep(1) # Wait for 1 second before retrying
                    continue
                else:
                    logger.error(f"Batch {batch_id} error: {e}")
                    with get_db_context() as session:
                        ErrorLogger.log_error(session, str(e))
                    return
            except Exception as e:
                logger.error(f"Batch {batch_id} error: {type(e).__name__} - {e}")
                with get_db_context() as session:
                    ErrorLogger.log_error(session, f"{type(e).__name__} - {e}")
                return
        else:
            logger.error(f"Batch {batch_id} failed after 3 retries.")
            return

        if isinstance(data, pd.DataFrame) and data.empty:
            return
        
        if not isinstance(data, dict):
            if len(batch_tickers) == 1:
                data = {batch_tickers[0]: data}
            else:
                return # Should not happen with group_by='ticker'

        with get_db_context() as session:
            engine_svc = RankingEngine(session, settings_obj) # Pass settings_obj
            
            for symbol in batch_tickers:
                try:
                    df = data.get(symbol)
                    
                    if df is None or df.empty:
                        logger.error(f"Error processing {symbol}: Data not found or empty dataframe.")
                        with get_db_context() as session:
                            ErrorLogger.log_error(session, f"Data not found or empty dataframe for ticker: {symbol}")
                        continue
                    df = df.dropna(subset=['Close'])
                    if len(df) < 200: continue

                    # Check Data Freshness (Optional but good)
                    if not MarketValidator.validate_market_data_freshness(df, settings_obj): # Pass settings_obj
                        continue

                    current_close = float(df['Close'].iloc[-1])
                    high_52 = float(df['High'].max())
                    low_52 = float(df['Low'].min())
                    
                    high_date_idx = df['High'].idxmax()
                    high_date = high_date_idx.date() if isinstance(high_date_idx, pd.Timestamp) else high_date_idx

                    if current_close < settings_obj.MIN_PRICE: continue # Use settings_obj
                    if not FraudDetector.basic_liquidity_check(df, current_close): continue
                    if current_close < (high_52 * 0.95): continue

                    logger.info(f"🔍 Analyzing Fundamentals: {symbol}...")
                    if settings_obj.FUNDAMENTAL_CHECK_ENABLED:
                        if FraudDetector.deep_fundamental_check(symbol, settings_obj): # Pass settings_obj
                                engine_svc.update_ranking(symbol, current_close, low_52, high_date)
                    else:
                        engine_svc.update_ranking(symbol, current_close, low_52, high_date)

                except Exception as e:
                    logger.error(f"Error processing {symbol}: {type(e).__name__} - {e}")
                    with get_db_context() as session:
                        ErrorLogger.log_error(session, f"{type(e).__name__} - {e}")
                    continue

    @staticmethod
    def scan_stocks_parallel(tickers: list[str], batch_size: int = 100, max_workers: int = 10):
        total = len(tickers)
        logger.info(f"Starting Parallel Scan for {total} stocks...")
        batches = [tickers[i:i + batch_size] for i in range(0, total, batch_size)]
        
        current_settings = get_settings() # Get settings here once
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = [executor.submit(StockFetcher.process_single_batch, batch, i+1, current_settings) for i, batch in enumerate(batches)]
            
            completed = 0
            for f in as_completed(futures):
                completed += 1
                logger.info(f"Progress: {completed}/{len(batches)} batches done.")
        finally:
            executor.shutdown(wait=True)

# --- CLASS 4: VALIDATOR ---
class MarketValidator:
    @staticmethod
    def should_run(settings_obj) -> bool: # Added settings_obj
        tz = zoneinfo.ZoneInfo(settings_obj.TIMEZONE)
        now = datetime.datetime.now(tz)
        if now.weekday() >= 5: return False
        return True

    @staticmethod
    def validate_market_data_freshness(df: pd.DataFrame, settings_obj) -> bool: # Added settings_obj
        """Checks if data is not older than 3 days."""
        if df.empty: return False
        tz = zoneinfo.ZoneInfo(settings_obj.TIMEZONE)
        today = datetime.datetime.now(tz).date()
        last_date = df.index[-1].date()
        delta = (today - last_date).days
        if delta > 3: return False
        return True

# --- CLASS 5: ERROR LOGGER ---
class ErrorLogger:
    @staticmethod
    def generate_error_code(length=8):
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for i in range(length))

    @staticmethod
    def log_error(session: Session, error_message: str):
        # Check if error already exists
        stmt = select(Error).where(Error.error_message == error_message)
        exists = session.execute(stmt).first()
        
        if not exists:
            error_code = ErrorLogger.generate_error_code()
            new_error = Error(error_code=error_code, error_message=error_message)
            session.add(new_error)
            session.commit()