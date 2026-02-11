import logging
import datetime
from datetime import date
import zoneinfo
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import select, desc, asc
from sqlalchemy.orm import Session
from src.config import get_settings
from src.models import MomentumStock, Error
from src.database import get_db_context
from src.utils import Bhavcopy
import secrets
import string
import time
import threading
import random
import json
import os
import requests
from bs4 import BeautifulSoup
import math

logger = logging.getLogger("Anveshq")
logger.setLevel(logging.INFO)
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

CACHE_FILE = "fundamentals_cache.json"
CACHE_EXPIRY_DAYS = 7

# --- CLASS 1: RISK AND QUALITY ANALYSIS ---
class RiskAndQualityAnalyzer:
    """
    Evaluates the risk and signal quality of a stock's momentum.

    This class provides static methods to perform various checks, including:
    - Liquidity analysis (relative volume and turnover)
    - Volume confirmation to validate price moves
    - Risk scoring based on volatility and other factors.
    
    It is important to note that this class does NOT perform fraud detection.
    """
    @staticmethod
    def get_fundamentals_from_google_finance(symbol: str) -> dict | None:
        """
        Scrapes Google Finance for key fundamentals as a fallback.
        """
        exchange = None
        if symbol.endswith(".NS"):
            exchange = "NSE"
        elif symbol.endswith(".BO"):
            exchange = "BOM"
        else:
            return None

        google_symbol = symbol.replace(".NS", "").replace(".BO", "") + f":{exchange}"
        url = f"https://www.google.com/finance/quote/{google_symbol}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # --- This is the brittle part ---
            # Find all divs that seem to contain financial data
            all_divs = soup.find_all('div', class_='gyH2C')
            
            fundamentals = {}
            
            for div in all_divs:
                if 'Market cap' in div.text:
                    value_div = div.find_next_sibling('div')
                    if value_div:
                        # Value is like '₹8.34T'. Need to parse it.
                        mc_text = value_div.text.strip().replace('₹', '')
                        if 'T' in mc_text:
                            mc_value = float(mc_text.replace('T', '')) * 1e12
                        elif 'B' in mc_text:
                            mc_value = float(mc_text.replace('B', '')) * 1e9
                        else:
                            mc_value = float(mc_text)
                        fundamentals['marketCap'] = mc_value
                
                if 'P/E ratio' in div.text:
                    value_div = div.find_next_sibling('div')
                    if value_div and value_div.text.strip() != '—':
                        fundamentals['trailingPE'] = float(value_div.text.strip())

            return fundamentals if fundamentals else None

        except Exception as e:
            logger.error(f"Error scraping Google Finance for {symbol}: {e}")
            return None

    @staticmethod
    def relative_liquidity_check(df: pd.DataFrame, settings_obj) -> tuple[bool, str | None]:
        """
        Relative Liquidity Check: 10D Median Turnover vs 180D Median Turnover.
        A stock's recent liquidity should not be abnormally low compared to its history.
        This check helps filter out stocks with liquidity and volume anomalies.
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
        Ensures the recent price move is backed by significant volume, a key aspect of signal quality validation.
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
        """
        Calculates a risk score based on price volatility, volume patterns, and other momentum quality indicators.
        A lower score indicates better momentum quality.
        """
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
                if not info: # yfinance can return an empty dict
                    raise ValueError("yfinance returned empty info dict")
            except Exception as e:
                # Try fast_info as a partial fallback for Market Cap (more robust than info)
                try:
                    fast_info = ticker.fast_info
                    mcap = fast_info.get('marketCap')
                    if mcap:
                        info = {'marketCap': mcap, 'trailingPE': None, 'debtToEquity': None}
                        logger.info(f"Recovered Market Cap for {symbol} using fast_info.")
                    else:
                        raise e
                except Exception:
                    logger.info(f"yfinance failed for {symbol}: {e}. Falling back to web scraping.")
                    try:
                        info = RiskAndQualityAnalyzer.get_fundamentals_from_google_finance(symbol)
                    except Exception as scrape_e:
                        logger.error(f"Web scraping failed for {symbol}: {scrape_e}")
                        # Fail open if both primary and fallback fail
                        return True 
            
            # Cache whatever result we got
            cache[symbol] = {
                'info': info,
                'timestamp': datetime.datetime.now().isoformat()
            }
            with open(CACHE_FILE, 'w') as f:
                json.dump(cache, f)

        if not info:
            logger.warning(f"Could not process fundamentals for {symbol}: 'info' is empty or None after fallback.")
            return True

        # --- Filtering Logic ---
        mcap = info.get('marketCap', 0)
        if mcap is None: # marketCap can be None
            mcap = 0
            
        if mcap < (settings_obj.MIN_MCAP_CRORES * 10_000_000):
            logger.info(f"REJECT {symbol}: Mcap too low ({mcap})")
            return False

        pe = info.get('trailingPE')
        if pe is not None and isinstance(pe, (int, float)) and pe < 0:
             logger.info(f"REJECT {symbol}: Loss Making (Negative PE)")
             return False
        
        dte = info.get('debtToEquity')
        if dte is not None and isinstance(dte, (int, float)) and dte > 3:
            logger.info(f"REJECT {symbol}: High Debt (D/E > 3)")
            return False

        return True

# --- CLASS 2: DB MANAGEMENT ---
class RankingEngine:
    def __init__(self, session: Session, settings_obj):
        self.session = session
        self.settings = settings_obj
        self.today = datetime.datetime.now(zoneinfo.ZoneInfo(self.settings.TIMEZONE)).date()

    def update_ranking(
        self,
        symbol: str,
        price: float,
        low_52_week_price: float,
        low_52_week_date: datetime.date,
        high_52_week_price: float,
        high_52_week_date: datetime.date,
        risk_score: int,
        is_volume_confirmed: bool,
        is_fundamental_ok: bool,
        company_name: str | None = None,
    ):
        # Critical field guardrail.
        if price is None or low_52_week_price is None or high_52_week_price is None:
            logger.warning("RANKING_UPDATE: SKIP %s due to missing critical values.", symbol)
            return False

        # Outlier detection for manual review.
        if price > 100000 or price < 1:
            logger.warning("RANKING_UPDATE: OUTLIER %s price %.2f flagged for review.", symbol, price)
            try:
                ErrorLogger.log_error(
                    self.session,
                    "Outlier Price Detected",
                    details={"symbol": symbol, "price": price, "date": str(self.today)},
                )
            except Exception as log_exc:
                logger.warning("Failed to persist outlier warning for %s: %s", symbol, log_exc)
            return False

        stmt = select(MomentumStock).where(MomentumStock.symbol == symbol)
        stock = self.session.execute(stmt).scalar_one_or_none()

        if stock and stock.last_seen_date == self.today:
            logger.info(f"RANKING_UPDATE: SKIP {symbol}. Already updated today.")
            return False
        
        if not stock:
            stock = MomentumStock(symbol=symbol, rank_score=1, last_seen_date=self.today)
            self.session.add(stock)
            logger.info(f"RANKING_UPDATE: NEW STOCK {symbol}. Initial rank: 1.")
        elif stock.last_seen_date < self.today:
            old_rank = stock.rank_score or 0
            stock.rank_score = min(old_rank + 1, min(self.settings.MAX_RANK, 100))
            stock.daily_rank_delta = stock.rank_score - old_rank
            logger.info(f"RANKING_UPDATE: INCREMENT {symbol}. Old rank: {old_rank}, New rank: {stock.rank_score}, Last seen: {stock.last_seen_date}, Today: {self.today}.")
        else:
            stock.daily_rank_delta = 0
            logger.info(f"RANKING_UPDATE: NO CHANGE {symbol}. Rank: {stock.rank_score}, Last seen: {stock.last_seen_date}, Today: {self.today}.")
        
        stock.current_price = price
        stock.low_52_week = low_52_week_price
        stock.low_52_week_date = low_52_week_date
        stock.high_52_week_price = high_52_week_price
        stock.high_52_week_date = high_52_week_date
        stock.last_seen_date = self.today
        stock.risk_score = risk_score
        stock.is_volume_confirmed = is_volume_confirmed
        stock.is_fundamental_ok = is_fundamental_ok
        stock.is_active = True
        if company_name is not None:
            stock.company_name = company_name
        return True

    def decay_unseen_ranks(self, seen_symbols: set[str]):
        logger.info(f"Decaying ranks for all stocks not in today's seen list ({len(seen_symbols)} symbols)...")
        try:
            stmt = select(MomentumStock).filter(MomentumStock.symbol.notin_(seen_symbols))
            stocks_to_decay = self.session.execute(stmt).scalars().all()
            if not stocks_to_decay:
                logger.info("No stocks to decay.")
                return
            for stock in stocks_to_decay:
                unseen_days = (self.today - stock.last_seen_date).days
                
                if unseen_days == 2:
                    stock.rank_score = max(0, stock.rank_score - 1)
                elif unseen_days == 3:
                    stock.rank_score = max(0, stock.rank_score - 2)
                elif unseen_days > 3:
                    stock.rank_score = 0
            self.session.commit()
            logger.info(f"Successfully decayed rank for {len(stocks_to_decay)} stocks.")
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error during rank decay process: {e}")
            with get_db_context() as error_session:
                ErrorLogger.log_error(error_session, "Rank Decay Error", details={"error": str(e)})

# --- CLASS 3: PARALLEL FETCHER ---
class StockFetcher:
    @staticmethod
    def get_top_movers(session: Session):
        stmt = select(MomentumStock).order_by(
            desc(MomentumStock.daily_rank_delta),
            desc(MomentumStock.rank_score),
            asc(MomentumStock.top10_hit_count)
        ).limit(10)
        return session.execute(stmt).scalars().all()

    @staticmethod
    def get_top_movers_with_repetition_control(session: Session, settings_obj, today: date):
        stmt = select(MomentumStock).order_by(
            desc(MomentumStock.daily_rank_delta),
            desc(MomentumStock.rank_score),
            asc(MomentumStock.top10_hit_count)
        )
        all_candidates = session.execute(stmt).scalars().all()

        top_10_list = []
        
        for stock in all_candidates:
            if len(top_10_list) >= 10:
                break

            if stock.last_top10_date and (today - stock.last_top10_date).days <= settings_obj.REPETITION_COOLDOWN_DAYS:
                if stock.daily_rank_delta < 2:
                    logger.info(f"REPETITION CONTROL: Skipping {stock.symbol} due to recent appearance.")
                    continue

            if not (stock.rank_score >= 3 and
                    stock.daily_rank_delta >= 1 and
                    stock.risk_score <= 3 and
                    stock.is_volume_confirmed and
                    stock.is_fundamental_ok):
                logger.info(f"GENUINE STRENGTH FILTER: Skipping {stock.symbol} due to not meeting criteria.")
                continue

            top_10_list.append(stock)

        for stock in top_10_list:
            stock.last_top10_date = today
            stock.top10_hit_count = (stock.top10_hit_count or 0) + 1
        
        session.commit()
        
        return top_10_list
        
    @staticmethod
    def process_single_batch(batch_tickers: list[str], batch_id: int, settings_obj, bhavcopy_df: pd.DataFrame) -> set[str]:
        logger.info(f"--- Starting Batch {batch_id} ---")
        qualified_symbols = set()
        with get_db_context() as session:
            try:
                engine_svc = RankingEngine(session, settings_obj)
                try:
                    existing_rows = session.execute(
                        select(MomentumStock.symbol, MomentumStock.last_seen_date).where(
                            MomentumStock.symbol.in_(batch_tickers)
                        )
                    ).all()
                    existing_today_symbols = {
                        sym for sym, last_seen in existing_rows if last_seen == engine_svc.today
                    }
                except Exception as e:
                    logger.warning(f"Could not prefetch existing ranks for batch {batch_id}: {e}")
                    existing_today_symbols = set()
                for symbol in batch_tickers:
                    try:
                        if symbol in existing_today_symbols:
                            logger.info(f"SKIP {symbol}: already updated today (idempotent scan).")
                            qualified_symbols.add(symbol)
                            continue
                        df_yf = yf.download(symbol, period="1y", progress=False, auto_adjust=True, timeout=10)
                        
                        # Flatten MultiIndex columns if present (fix for yfinance returning (Price, Ticker) columns)
                        if isinstance(df_yf.columns, pd.MultiIndex):
                            df_yf.columns = df_yf.columns.get_level_values(0)
                        
                        # FIX: Remove duplicate columns (caused by flattening MultiIndex sometimes)
                        df_yf = df_yf.loc[:, ~df_yf.columns.duplicated()]
                        
                        # FIX: Remove duplicate index dates (clean up yfinance data)
                        df_yf = df_yf[~df_yf.index.duplicated(keep='last')]

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

                        is_liquid, liq_reason = RiskAndQualityAnalyzer.relative_liquidity_check(df, settings_obj)
                        if not is_liquid:
                            logger.info(f"SKIP {symbol}: {liq_reason}")
                            continue

                        is_confirmed, vol_reason = RiskAndQualityAnalyzer.volume_confirmation(df, settings_obj)
                        if not is_confirmed:
                            logger.info(f"SKIP {symbol}: {vol_reason}")
                            continue
                            
                        is_fundamental_ok = RiskAndQualityAnalyzer.deep_fundamental_check(symbol, settings_obj)
                        if not is_fundamental_ok:
                            continue

                        risk_score, risk_reasons = RiskAndQualityAnalyzer.calculate_risk_score(df, current_close, high_52)
                        logger.info(f"QUALIFIED: {symbol} | Price: {current_close:.2f} | Risk: {risk_score} ({', '.join(risk_reasons)})")
                        
                        company_name = None
                        try:
                            info = yf.Ticker(symbol).info
                            company_name = (info.get("shortName") or info.get("longName")) if info else None
                            if isinstance(company_name, str):
                                company_name = company_name.strip() or None
                        except Exception:
                            pass
                        
                        high_date_idx = df['High'].idxmax()
                        high_date = high_date_idx.date() if isinstance(high_date_idx, pd.Timestamp) else high_date_idx
                        
                        low_date_idx = df['Low'].idxmin()
                        low_date = low_date_idx.date() if isinstance(low_date_idx, pd.Timestamp) else low_date_idx

                        engine_svc.update_ranking(
                            symbol,
                            current_close,
                            float(df['Low'].min()),
                            low_date,
                            float(df['High'].max()),
                            high_date,
                            risk_score,
                            is_confirmed,
                            is_fundamental_ok,
                            company_name=company_name,
                        )
                        qualified_symbols.add(symbol)
                    except Exception as e:
                        logger.error(f"Error processing {symbol}: {type(e).__name__} - {e}", exc_info=True)
                        try:
                            ErrorLogger.log_error(
                                session,
                                f"Processing Error: {type(e).__name__}",
                                details={"symbol": symbol, "batch_id": batch_id, "error": str(e)},
                            )
                        except Exception as log_exc:
                            logger.warning(
                                "Failed to write processing error for %s in batch %s: %s",
                                symbol,
                                batch_id,
                                log_exc,
                            )
                        continue
                logger.info(f"--- Finished Batch {batch_id}, Committing {len(qualified_symbols)} updates ---")
            except Exception as e:
                logger.error(f"--- Batch {batch_id} failed, rolling back ---", exc_info=True)
                session.rollback()
                with get_db_context() as error_session:
                    ErrorLogger.log_error(
                        error_session,
                        f"Batch Processing Error: {type(e).__name__}",
                        details={"batch_id": batch_id, "error": str(e)},
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

        base_batch_size = max(1, int(batch_size))
        min_batches = 10
        max_batches = 15
        target_batches = math.ceil(total / base_batch_size)
        target_batches = max(min_batches, target_batches)
        target_batches = min(max_batches, target_batches, total)
        effective_batch_size = math.ceil(total / target_batches)

        logger.info(
            f"Batching configuration: total={total}, batches={target_batches}, batch_size={effective_batch_size}"
        )

        batches = [
            filtered_tickers[i:i + effective_batch_size]
            for i in range(0, total, effective_batch_size)
        ]
        current_settings = get_settings()
        all_qualified_symbols = set()
        effective_workers = min(max_workers, len(batches))
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
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
    # Hardcoded list of market holidays for early-exit checks.
    # This avoids making API calls on known holidays.
    HOLIDAYS = [
        date(2025, 1, 26), # Republic Day
        date(2025, 3, 25), # Holi
        date(2025, 4, 14), # Dr. Ambedkar Jayanti
        date(2025, 4, 21), # Ram Navami
        date(2025, 5, 1),  # Maharashtra Day
        date(2025, 8, 15), # Independence Day
        date(2025, 10, 2), # Gandhi Jayanti
        date(2025, 11, 4), # Diwali
        date(2025, 12, 25) # Christmas
    ]

    @staticmethod
    def should_run(settings_obj) -> bool:
        tz = zoneinfo.ZoneInfo(settings_obj.TIMEZONE)
        now = datetime.datetime.now(tz)
        
        # 1. Weekend Check
        if now.weekday() >= 5: 
            logger.info("Skipping run: It's a weekend.")
            return False
            
        # 2. Hardcoded Holiday Check
        if now.date() in MarketValidator.HOLIDAYS:
            logger.info(f"Skipping run: Today ({now.date()}) is a known market holiday.")
            return False

        # 3. Bhavcopy Availability Check (as a proxy for market open)
        try:
            latest_bhavcopy_date = Bhavcopy.find_latest_available_date(
                now.date(), settings_obj, max_lookback_days=7
            )
            if latest_bhavcopy_date is None:
                if settings_obj.MODE == "DEV":
                    logger.warning("Bhavcopy not available in the last 7 days. Proceeding in DEV mode.")
                    return True
                logger.info("Skipping run: Bhavcopy not available in the last 7 days.")
                return False
            if latest_bhavcopy_date != now.date():
                logger.warning(
                    f"Bhavcopy not available for today. Using latest available date: {latest_bhavcopy_date}."
                )
        except Exception as e:
            logger.error(f"Skipping run due to error checking Bhavcopy: {e}")
            return False

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
        stmt = select(Error.id).where(Error.error_message == error_message).limit(1)
        exists = session.execute(stmt).scalar_one_or_none()
        if exists is None:
            error_code = ErrorLogger.generate_error_code()
            new_error = Error(
                error_code=error_code, 
                error_message=error_message,
                error_details=details
            )
            session.add(new_error)
