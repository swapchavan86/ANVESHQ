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

# --- CLASS 1: QUALITY, RISK & SCORING ---
class FraudDetector:
    @staticmethod
    def relative_liquidity_check(df: pd.DataFrame) -> tuple[bool, str | None]:
        """
        Relative Liquidity Check: 10D Median Turnover vs 180D Median Turnover.
        A stock's recent liquidity should not be abnormally low compared to its history.
        """
        if len(df) < 180: return False, "Insufficient history for liquidity check"
        
        df['Turnover'] = df['Close'] * df['Volume']
        median_turnover_10d = df['Turnover'].tail(10).median()
        median_turnover_180d = df['Turnover'].tail(180).median()

        if median_turnover_180d == 0: return False, "Zero median turnover in last 180 days"

        # Allow recent turnover to be slightly lower, but not drastically.
        # e.g., if recent is 0.6 of historical, it's a potential flag.
        if (median_turnover_10d / median_turnover_180d) < 0.7:
            return False, f"Relative liquidity failure ({median_turnover_10d:.2f} vs {median_turnover_180d:.2f})"
        return True, None

    @staticmethod
    def volume_confirmation(df: pd.DataFrame) -> tuple[bool, str | None]:
        """
        Volume Confirmation: 5D Avg Volume must be 1.5x of 30D Avg Volume.
        Ensures the recent price move is backed by significant volume.
        """
        if len(df) < 30: return False, "Insufficient history for volume confirmation"
        
        avg_vol_5d = df['Volume'].tail(5).mean()
        avg_vol_30d = df['Volume'].tail(30).mean()

        if avg_vol_30d == 0: return False, "Zero average volume in last 30 days"

        if (avg_vol_5d / avg_vol_30d) < 1.5:
            return False, f"Weak volume confirmation ({avg_vol_5d:.0f} vs {avg_vol_30d:.0f})"
        return True, None
    
    @staticmethod
    def calculate_risk_score(df: pd.DataFrame, current_price: float, high_52: float) -> tuple[int, list[str]]:
        """
        Calculates a risk score from 0-7 based on additive penalties.
        This is for warning purposes, not filtering.
        """
        risk_score = 0
        risk_reasons = []

        # Risk 1: Pump-like single day spike
        if not df.empty and df['Close'].iloc[-1] / df['Close'].iloc[-2] > 1.12:
            risk_score += 2
            risk_reasons.append("Single-day spike > 12%")
        
        # Risk 2: Volume Inconsistency (potential low-quality moves)
        if len(df) > 10:
            median_vol = df['Volume'].tail(10).median()
            max_vol = df['Volume'].tail(10).max()
            if max_vol > 0 and (median_vol / max_vol) < 0.25:
                risk_score += 2
                risk_reasons.append("High volume inconsistency")

        # Risk 3: Weak Momentum Smoothness (choppy price action)
        if len(df) > 10:
            positive_closes = (df['Close'].tail(10).pct_change() > 0).sum()
            if positive_closes < 4:
                risk_score += 1
                risk_reasons.append("Choppy momentum (<4 positive days in last 10)")
        
        # Risk 4: Overextension (very close to 52w high)
        if current_price >= (high_52 * 0.99):
            risk_score += 1
            risk_reasons.append("Price is near 52-week high peak")
        
        # Risk 5: Low absolute liquidity despite passing relative check
        avg_turnover_10d = (df['Close'] * df['Volume']).tail(10).mean()
        if avg_turnover_10d < 10_000_000: # Below 1 Cr turnover
            risk_score += 1
            risk_reasons.append("Low absolute turnover (<1 Cr)")

        return min(risk_score, 7), risk_reasons[:3] # Cap score at 7, max 3 reasons

    @staticmethod
    def deep_fundamental_check(symbol: str, settings_obj) -> bool:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.get('info', {})
            
            mcap = info.get('marketCap', 0)
            if mcap is not None and mcap < (settings_obj.MIN_MCAP_CRORES * 10_000_000):
                logger.info(f"❌ REJECT {symbol}: Mcap too low ({mcap})")
                return False

            pe = info.get('trailingPE')
            if pe is not None and pe < 0:
                 logger.info(f"❌ REJECT {symbol}: Loss Making (Negative PE)")
                 return False
            
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
    def __init__(self, session: Session, settings_obj):
        self.session = session
        self.settings = settings_obj
        self.today = datetime.datetime.now(zoneinfo.ZoneInfo(self.settings.TIMEZONE)).date()

    def update_ranking(self, symbol: str, price: float, low_52: float, high_date: datetime.date):
        """
        Updates a stock's rank upon qualification. Creates the stock if it's new.
        Initial rank is 0, qualified rank becomes 1.
        """
        stmt = select(MomentumStock).where(MomentumStock.symbol == symbol)
        stock = self.session.execute(stmt).scalar_one_or_none()

        if not stock:
            stock = MomentumStock(
                symbol=symbol,
                rank_score=0, # Initial rank before qualification
                last_seen_date=self.today,
            )
            self.session.add(stock)
            logger.info(f"✨ NEW STOCK: {symbol} created with initial rank 0.")

        # Apply on-qualify rule: rank = min(rank + 1, MAX_RANK)
        # (stock.rank_score or 0) handles potential nulls from DB
        stock.rank_score = min((stock.rank_score or 0) + 1, self.settings.MAX_RANK)
        
        # Update data
        stock.current_price = price
        stock.low_52_week = low_52
        stock.high_52_week_date = high_date
        stock.last_seen_date = self.today
        
        try:
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error committing {symbol}: {e}")
            with get_db_context() as session:
                ErrorLogger.log_error(session, str(e))

    def decay_unseen_ranks(self, seen_symbols: set[str]):
        """
        Decays the rank of all stocks that were NOT seen in the current run.
        This is crucial for the Decaying Rank system.
        """
        logger.info(f"Decaying ranks for all stocks not in today's seen list ({len(seen_symbols)} symbols)...")
        
        try:
            stmt = select(MomentumStock).filter(
                MomentumStock.symbol.notin_(seen_symbols)
            )
            stocks_to_decay = self.session.execute(stmt).scalars().all()

            if not stocks_to_decay:
                logger.info("No stocks to decay.")
                return

            for stock in stocks_to_decay:
                # Rule: rank = floor(rank * DECAY_FACTOR)
                # (stock.rank_score or 0) handles nulls, treating them as 0.
                new_rank = (stock.rank_score or 0) * self.settings.DECAY_FACTOR
                stock.rank_score = max(0, int(new_rank)) # int() floors the float

            self.session.commit()
            logger.info(f"Successfully decayed rank for {len(stocks_to_decay)} stocks.")
        
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error during rank decay process: {e}")
            with get_db_context() as session:
                ErrorLogger.log_error(session, f"Rank Decay Error: {e}")


# --- CLASS 3: PARALLEL FETCHER ---
class StockFetcher:
    @staticmethod
    def process_single_batch(batch_tickers: list[str], batch_id: int, settings_obj) -> set[str]:
        logger.info(f"--- Starting Batch {batch_id} ---")
        qualified_symbols = set()
        
        try:
            data = yf.download(batch_tickers, period="1y", group_by='ticker', threads=False, progress=False, auto_adjust=True)
        except Exception as e:
            logger.error(f"Batch {batch_id} download failed with exception: {e}")
            return qualified_symbols

        if data.empty:
            return qualified_symbols

        with get_db_context() as session:
            engine_svc = RankingEngine(session, settings_obj)
            
            for symbol in batch_tickers:
                try:
                    df = None
                    if isinstance(data, dict):
                        df = data.get(symbol)
                    elif isinstance(data, pd.DataFrame):
                        # Handle multi-level columns if symbol exists
                        if symbol in data.columns.get_level_values(1):
                             df = data.xs(symbol, level=1, axis=1)
                        # Handle single-level columns for single-ticker batches
                        elif len(batch_tickers) == 1:
                            df = data

                    if df is None or df.empty or 'Close' not in df:
                        continue
                    
                    df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
                    if len(df) < 200: continue

                    if not MarketValidator.validate_market_data_freshness(df, settings_obj):
                        continue

                    current_close = float(df['Close'].iloc[-1])
                    high_52 = float(df['High'].max())
                    low_52 = float(df['Low'].min())
                    
                    # --- FILTERING LOGIC ---
                    if current_close < settings_obj.MIN_PRICE: continue
                    if current_close < (high_52 * 0.90): continue

                    is_liquid, _ = FraudDetector.relative_liquidity_check(df)
                    if not is_liquid: continue

                    is_confirmed, _ = FraudDetector.volume_confirmation(df)
                    if not is_confirmed: continue
                        
                    if settings_obj.FUNDAMENTAL_CHECK_ENABLED:
                        if not FraudDetector.deep_fundamental_check(symbol, settings_obj):
                            continue

                    # --- PASSED ALL FILTERS ---
                    risk_score, risk_reasons = FraudDetector.calculate_risk_score(df, current_close, high_52)
                    logger.info(f"✅ QUALIFIED: {symbol} | Price: {current_close:.2f} | Risk: {risk_score} ({', '.join(risk_reasons)})")

                    # --- PERSISTENCE ---
                    high_date_idx = df['High'].idxmax()
                    high_date = high_date_idx.date() if isinstance(high_date_idx, pd.Timestamp) else high_date_idx
                    
                    engine_svc.update_ranking(symbol, current_close, low_52, high_date)
                    qualified_symbols.add(symbol)

                except Exception as e:
                    logger.error(f"Error processing {symbol}: {type(e).__name__} - {e}")
                    with get_db_context() as session:
                        ErrorLogger.log_error(session, f"Processing Error for {symbol}: {type(e).__name__} - {e}")
                    continue
        return qualified_symbols

    @staticmethod
    def scan_stocks_parallel(tickers: list[str], batch_size: int = 100, max_workers: int = 10):
        total = len(tickers)
        logger.info(f"Starting Parallel Scan for {total} stocks...")
        batches = [tickers[i:i + batch_size] for i in range(0, total, batch_size)]
        
        current_settings = get_settings()
        all_qualified_symbols = set()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {executor.submit(StockFetcher.process_single_batch, batch, i+1, current_settings): i for i, batch in enumerate(batches)}
            
            for future in as_completed(future_to_batch):
                batch_num = future_to_batch[future] + 1
                try:
                    qualified_in_batch = future.result()
                    all_qualified_symbols.update(qualified_in_batch)
                    logger.info(f"Progress: Batch {batch_num}/{len(batches)} done. Found {len(qualified_in_batch)} qualified stocks.")
                except Exception as exc:
                    logger.error(f'Batch {batch_num} generated an exception: {exc}')

        # --- After all batches are done, decay ranks of unseen stocks ---
        if all_qualified_symbols:
            with get_db_context() as session:
                engine_svc = RankingEngine(session, current_settings)
                engine_svc.decay_unseen_ranks(all_qualified_symbols)
        else:
            logger.warning("No stocks qualified in this run. Skipping rank decay.")
        
        logger.info("Parallel Scan Complete.")

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