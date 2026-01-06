import logging
import datetime
import zoneinfo
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config import get_settings
from src.models import MomentumStock, Error
from src.database import get_db_context
from src.utils import Bhavcopy
import secrets
import string
import time
import threading
import json
import os

logger = logging.getLogger("Nexara")
logger.setLevel(logging.INFO)
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

CACHE_FILE = "fundamentals_cache.json"
CACHE_EXPIRY_DAYS = 7

# --- CLASS 1: QUALITY, RISK & SCORING ---
class FraudDetector:
    @staticmethod
    def relative_liquidity_check(df: pd.DataFrame, settings_obj) -> tuple[bool, str | None]:
        """
        Relative Liquidity Check: 10D Median Turnover vs 180D Median Turnover.
        A stock's recent liquidity should not be abnormally low compared to its history.
        """
        if len(df) < 180: return False, "Insufficient history for liquidity check"
        
        turnover = df['Close'] * df['Volume']
        median_turnover_10d = turnover.tail(10).median()
        median_turnover_180d = turnover.tail(180).median()

        if median_turnover_180d == 0: return False, "Zero median turnover in last 180 days"

        if (median_turnover_10d / median_turnover_180d) < settings_obj.RELATIVE_LIQUIDITY_FACTOR:
            return False, f"Relative liquidity failure ({median_turnover_10d:.2f} vs {median_turnover_180d:.2f})"
        return True, None

    @staticmethod
    def volume_confirmation(df: pd.DataFrame, settings_obj) -> tuple[bool, str | None]:
        """
        Volume Confirmation: 5D Avg Volume must be X times of 30D Avg Volume.
        Ensures the recent price move is backed by significant volume.
        """
        if len(df) < 30: return False, "Insufficient history for volume confirmation"
        
        avg_vol_5d = df['Volume'].tail(5).mean()
        avg_vol_30d = df['Volume'].tail(30).mean()

        if avg_vol_30d == 0: return False, "Zero average volume in last 30 days"

        if (avg_vol_5d / avg_vol_30d) < settings_obj.VOLUME_CONFIRMATION_FACTOR:
            return False, f"Weak volume confirmation ({avg_vol_5d:.0f} vs {avg_vol_30d:.0f})"
        return True, None
    
    @staticmethod
    def calculate_risk_score(df: pd.DataFrame, current_price: float, high_52: float) -> tuple[int, list[str]]:
        risk_score = 0
        risk_reasons = []
        if not df.empty and df['Close'].iloc[-1] / df['Close'].iloc[-2] > 1.12:
            risk_score += 2
            risk_reasons.append("Single-day spike > 12%")
        if len(df) > 10:
            median_vol = df['Volume'].tail(10).median()
            max_vol = df['Volume'].tail(10).max()
            if max_vol > 0 and (median_vol / max_vol) < 0.25:
                risk_score += 2
                risk_reasons.append("High volume inconsistency")
        if len(df) > 10:
            positive_closes = (df['Close'].tail(10).pct_change() > 0).sum()
            if positive_closes < 4:
                risk_score += 1
                risk_reasons.append("Choppy momentum (<4 positive days in last 10)")
        if current_price >= (high_52 * 0.99):
            risk_score += 1
            risk_reasons.append("Price is near 52-week high peak")
        avg_turnover_10d = (df['Close'] * df['Volume']).tail(10).mean()
        if avg_turnover_10d < 10_000_000:
            risk_score += 1
            risk_reasons.append("Low absolute turnover (<1 Cr)")
        return min(risk_score, 7), risk_reasons[:3]

    @staticmethod
    def deep_fundamental_check(symbol: str, settings_obj) -> bool:
        
        # --- Caching Logic ---
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                try:
                    cache = json.load(f)
                except json.JSONDecodeError:
                    cache = {}
        else:
            cache = {}

        if symbol in cache:
            cached_data = cache[symbol]
            last_fetched = datetime.datetime.fromisoformat(cached_data['timestamp']).date()
            if (datetime.date.today() - last_fetched).days < CACHE_EXPIRY_DAYS:
                info = cached_data['info']
            else:
                info = None
        else:
            info = None

        if info is None:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                cache[symbol] = {
                    'info': info,
                    'timestamp': datetime.datetime.now().isoformat()
                }
                with open(CACHE_FILE, 'w') as f:
                    json.dump(cache, f)
            except Exception as e:
                logger.warning(f"Could not fetch fundamentals for {symbol}: {e}")
                return True # Default to True if yfinance fails

        # --- Filtering Logic ---
        mcap = info.get('marketCap', 0)
        if mcap < (settings_obj.MIN_MCAP_CRORES * 10_000_000):
            logger.info(f"REJECT {symbol}: Mcap too low ({mcap})")
            return False

        pe = info.get('trailingPE')
        if isinstance(pe, (int, float)) and pe < 0:
             logger.info(f"REJECT {symbol}: Loss Making (Negative PE)")
             return False
        
        dte = info.get('debtToEquity')
        if isinstance(dte, (int, float)) and dte > 3:
            logger.info(f"REJECT {symbol}: High Debt (D/E > 3)")
            return False

        return True

# --- CLASS 2: DB MANAGEMENT ---
class RankingEngine:
    def __init__(self, session: Session, settings_obj):
        self.session = session
        self.settings = settings_obj
        self.today = datetime.datetime.now(zoneinfo.ZoneInfo(self.settings.TIMEZONE)).date()

    def update_ranking(self, symbol: str, price: float, low_52: float, high_date: datetime.date):
        stmt = select(MomentumStock).where(MomentumStock.symbol == symbol)
        stock = self.session.execute(stmt).scalar_one_or_none()
        
        if not stock:
            stock = MomentumStock(symbol=symbol, rank_score=0, last_seen_date=self.today)
            self.session.add(stock)
            logger.info(f"NEW STOCK: {symbol} created with initial rank 0.")
        
        # Only increment rank if the stock has not been seen today
        if stock.last_seen_date < self.today:
            stock.rank_score = min((stock.rank_score or 0) + 1, self.settings.MAX_RANK)
        
        stock.current_price = price
        stock.low_52_week = low_52
        stock.high_52_week_date = high_date
        stock.last_seen_date = self.today

    def decay_unseen_ranks(self, seen_symbols: set[str]):
        logger.info(f"Decaying ranks for all stocks not in today's seen list ({len(seen_symbols)} symbols)...")
        try:
            stmt = select(MomentumStock).filter(MomentumStock.symbol.notin_(seen_symbols))
            stocks_to_decay = self.session.execute(stmt).scalars().all()
            if not stocks_to_decay:
                logger.info("No stocks to decay.")
                return
            for stock in stocks_to_decay:
                new_rank = (stock.rank_score or 0) * self.settings.DECAY_FACTOR
                stock.rank_score = max(0, int(new_rank))
            self.session.commit()
            logger.info(f"Successfully decayed rank for {len(stocks_to_decay)} stocks.")
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error during rank decay process: {e}")
            with get_db_context() as session:
                ErrorLogger.log_error(session, "Rank Decay Error", details={"error": str(e)})

# --- CLASS 3: PARALLEL FETCHER ---
class StockFetcher:
    @staticmethod
    def process_single_batch(batch_tickers: list[str], batch_id: int, settings_obj, bhavcopy_df: pd.DataFrame) -> set[str]:
        logger.info(f"--- Starting Batch {batch_id} ---")
        qualified_symbols = set()
        with get_db_context() as session:
            try:
                engine_svc = RankingEngine(session, settings_obj)
                for symbol in batch_tickers:
                    try:
                        df_yf = yf.download(symbol, period="1y", progress=False, auto_adjust=True, timeout=10)
                        
                        symbol_without_suffix = symbol.split('.')[0]
                        daily_data_row = bhavcopy_df[bhavcopy_df['TckrSymb'] == symbol_without_suffix]

                        if not daily_data_row.empty:
                            daily_data = daily_data_row.iloc[0]
                            today_date = pd.to_datetime(daily_data['BizDt'])
                            if not df_yf.empty and df_yf.index[-1].date() == today_date.date():
                                df_yf = df_yf.iloc[:-1]
                            new_row = pd.DataFrame({
                                'Open': [daily_data['OpnPric']], 'High': [daily_data['HghPric']],
                                'Low': [daily_data['LwPric']], 'Close': [daily_data['ClsPric']],
                                'Volume': [daily_data['TtlTradgVol']]
                            }, index=[today_date])
                            df = pd.concat([df_yf, new_row]) if not df_yf.empty else new_row
                        else:
                            df = df_yf

                        if df.empty:
                            logger.info(f"SKIP {symbol}: No data available.")
                            continue
                        
                        if len(df) < 200:
                            logger.info(f"SKIP {symbol}: Insufficient data (< 200 days).")
                            continue

                        if not MarketValidator.validate_market_data_freshness(df, settings_obj):
                            logger.info(f"SKIP {symbol}: Stale data.")
                            continue

                        current_close = float(df['Close'].iloc[-1])
                        high_52 = float(df['High'].max())
                        
                        if current_close < settings_obj.MIN_PRICE:
                            logger.info(f"SKIP {symbol}: Price ({current_close:.2f}) < MIN_PRICE ({settings_obj.MIN_PRICE}).")
                            continue

                        if current_close < (high_52 * settings_obj.NEAR_52_WEEK_HIGH_THRESHOLD):
                            logger.info(f"SKIP {symbol}: Price not near 52-week high.")
                            continue

                        is_liquid, liq_reason = FraudDetector.relative_liquidity_check(df, settings_obj)
                        if not is_liquid:
                            logger.info(f"SKIP {symbol}: {liq_reason}")
                            continue

                        is_confirmed, vol_reason = FraudDetector.volume_confirmation(df, settings_obj)
                        if not is_confirmed:
                            logger.info(f"SKIP {symbol}: {vol_reason}")
                            continue
                            
                        if settings_obj.FUNDAMENTAL_CHECK_ENABLED:
                            if not FraudDetector.deep_fundamental_check(symbol, settings_obj):
                                continue

                        risk_score, risk_reasons = FraudDetector.calculate_risk_score(df, current_close, high_52)
                        logger.info(f"QUALIFIED: {symbol} | Price: {current_close:.2f} | Risk: {risk_score} ({', '.join(risk_reasons)})")
                        
                        high_date_idx = df['High'].idxmax()
                        high_date = high_date_idx.date() if isinstance(high_date_idx, pd.Timestamp) else high_date_idx
                        engine_svc.update_ranking(symbol, current_close, float(df['Low'].min()), high_date)
                        qualified_symbols.add(symbol)
                    except Exception as e:
                        logger.error(f"Error processing {symbol}: {type(e).__name__} - {e}", exc_info=True)
                        with get_db_context() as error_session:
                            ErrorLogger.log_error(
                                error_session, 
                                f"Processing Error: {type(e).__name__}", 
                                details={"symbol": symbol, "batch_id": batch_id, "error": str(e)}
                            )
                        continue
                session.commit()
                logger.info(f"--- Finished Batch {batch_id}, Committing {len(qualified_symbols)} updates ---")
            except Exception as e:
                logger.error(f"--- Batch {batch_id} failed, rolling back ---", exc_info=True)
                session.rollback()
                with get_db_context() as error_session:
                    ErrorLogger.log_error(
                        error_session, 
                        f"Batch Processing Error: {type(e).__name__}", 
                        details={"batch_id": batch_id, "error": str(e)}
                    )
            return qualified_symbols
    @staticmethod
    def scan_stocks_parallel(tickers: list[str], batch_size: int = 100, max_workers: int = 10):
        
        # --- Deduplicate tickers ---
        tickers = list(set(tickers))

        bhavcopy_df = Bhavcopy.get_bhavcopy_data()
        
        if bhavcopy_df.empty:
            logger.warning("Could not get Bhavcopy data. Proceeding with full universe as fallback.")
            filtered_tickers = tickers
        else:
            bhavcopy_symbols = set(bhavcopy_df['TckrSymb'].unique())
            logger.info(f"Loaded {len(bhavcopy_symbols)} unique symbols from Bhavcopy.")
            filtered_tickers = [t for t in tickers if t.split('.')[0] in bhavcopy_symbols]
            logger.info(f"Universe filtered to {len(filtered_tickers)} actively traded stocks.")
        total = len(filtered_tickers)
        if total == 0:
            logger.warning("No tickers to scan. Aborting.")
            return
        logger.info(f"Starting Parallel Scan for {total} stocks...")
        batches = [filtered_tickers[i:i + batch_size] for i in range(0, total, batch_size)]
        current_settings = get_settings()
        all_qualified_symbols = set()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {executor.submit(StockFetcher.process_single_batch, batch, i+1, current_settings, bhavcopy_df): i for i, batch in enumerate(batches)}
            for future in as_completed(future_to_batch):
                batch_num = future_to_batch[future] + 1
                try:
                    qualified_in_batch = future.result()
                    all_qualified_symbols.update(qualified_in_batch)
                    logger.info(f"Progress: Batch {batch_num}/{len(batches)} done. Found {len(qualified_in_batch)} qualified.")
                except Exception as exc:
                    logger.error(f'Batch {batch_num} generated an exception: {exc}', exc_info=True)
        if all_qualified_symbols:
            with get_db_context() as session:
                engine_svc = RankingEngine(session, current_settings)
                engine_svc.decay_unseen_ranks(all_qualified_symbols)
        else:
            logger.warning("No stocks qualified in this run. Skipping rank decay.")
        logger.info("Fluxmind scan complete.")

# --- CLASS 4: VALIDATOR ---
class MarketValidator:
    @staticmethod
    def should_run(settings_obj) -> bool:
        tz = zoneinfo.ZoneInfo(settings_obj.TIMEZONE)
        now = datetime.datetime.now(tz)
        if now.weekday() >= 5: return False
        return True

    @staticmethod
    def validate_market_data_freshness(df: pd.DataFrame, settings_obj) -> bool:
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
    def log_error(session: Session, error_message: str, details: dict = None):
        stmt = select(Error).where(Error.error_message == error_message)
        exists = session.execute(stmt).first()
        if not exists:
            error_code = ErrorLogger.generate_error_code()
            new_error = Error(
                error_code=error_code, 
                error_message=error_message,
                error_details=details
            )
            session.add(new_error)
            session.commit()