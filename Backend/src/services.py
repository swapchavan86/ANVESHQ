import logging
import datetime
from datetime import date
import zoneinfo
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import select, desc, asc
from sqlalchemy.orm import Session
from src.config import get_settings
from src.models import MomentumStock, Error
from src.database import get_db_context
from src.earnings_calendar import EarningsCalendar
from src.position_sizing import PositionSizer
from src.utils import Bhavcopy
from src.yahoo_finance import download_history, get_company_name, get_fast_info, get_info, get_ticker
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
import re

logger = logging.getLogger("Anveshq")
logger.setLevel(logging.INFO)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

CACHE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fundamentals_cache.json"))
CACHE_EXPIRY_DAYS = 7
_regime_cache: dict[datetime.date, bool] = {}
_MARKET_REGIME_CACHE = _regime_cache
_NIFTY_RS_CACHE: dict[datetime.date, pd.DataFrame] = {}


def _get_regime_cache() -> dict:
    preferred = globals().get("_regime_cache", {})
    legacy = globals().get("_MARKET_REGIME_CACHE", preferred)
    if preferred is not legacy:
        if not preferred:
            return preferred
        if not legacy:
            return legacy
    return preferred


def _parse_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).replace(",", "").replace("₹", "").strip()
    if not text or text in {"-", "--", "—"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_market_cap(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).replace(",", "").replace("₹", "").strip().upper()
    number = _parse_number(text)
    if number is None:
        return None
    if "CR" in text:
        return number * 10_000_000
    if "LAC" in text or "LAKH" in text:
        return number * 100_000
    if "T" in text or "TRILLION" in text:
        return number * 1_000_000_000_000
    if "B" in text or "BILLION" in text:
        return number * 1_000_000_000
    if "M" in text or "MILLION" in text:
        return number * 1_000_000
    return number


def _cap_band(market_cap: float | None) -> str | None:
    if market_cap is None:
        return None
    crore = market_cap / 10_000_000
    if crore >= 50_000:
        return "LARGE_CAP"
    if crore >= 5_000:
        return "MID_CAP"
    return "SMALL_CAP"

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

            fundamentals = {}
            selectors = ['gyH2C', 'P6K39c', 'YMlKec', 'mfs7Fc']
            nodes = []
            for selector in selectors:
                nodes.extend(soup.find_all(class_=selector))

            label_nodes = soup.find_all(string=re.compile(r"Market cap|P/E ratio", re.I))
            nodes.extend(node.parent for node in label_nodes if getattr(node, "parent", None) is not None)

            for node in nodes:
                text = node.get_text(" ", strip=True)
                sibling = node.find_next_sibling()
                sibling_text = sibling.get_text(" ", strip=True) if sibling else ""
                combined = f"{text} {sibling_text}".strip()
                if "Market cap" in combined:
                    fundamentals["marketCap"] = fundamentals.get("marketCap") or _parse_market_cap(sibling_text or text)
                if "P/E ratio" in combined:
                    fundamentals["trailingPE"] = fundamentals.get("trailingPE") or _parse_number(sibling_text or text)

            return fundamentals if fundamentals else None

        except Exception as e:
            logger.error(f"Error scraping Google Finance for {symbol}: {e}")
            return None

    @staticmethod
    def get_fundamentals_from_nse(symbol: str) -> dict | None:
        if not symbol.endswith(".NS"):
            return None
        base_symbol = symbol.replace(".NS", "")
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.nseindia.com/",
        }
        try:
            session.get("https://www.nseindia.com", headers=headers, timeout=10)
            response = session.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={base_symbol}",
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            price_info = payload.get("priceInfo") if isinstance(payload.get("priceInfo"), dict) else {}
            security_info = payload.get("securityInfo") if isinstance(payload.get("securityInfo"), dict) else {}
            info_block = payload.get("info") if isinstance(payload.get("info"), dict) else {}
            last_price = _parse_number(price_info.get("lastPrice"))
            issued_size = _parse_number(security_info.get("issuedSize"))
            market_cap = _parse_market_cap(payload.get("marketCap") or payload.get("marketCapFull"))
            if market_cap is None and issued_size is not None and last_price is not None:
                market_cap = issued_size * last_price
            result = {
                "marketCap": market_cap,
                "trailingPE": _parse_number(price_info.get("pE") or payload.get("pE")),
                "sector": info_block.get("industry") or payload.get("industry"),
            }
            return {key: value for key, value in result.items() if value is not None}
        except Exception as exc:
            logger.warning("NSE fundamentals fallback failed for %s: %s", symbol, exc)
            return None

    @staticmethod
    def get_fundamentals_from_screener(symbol: str) -> dict | None:
        base_symbol = symbol.replace(".NS", "").replace(".BO", "")
        url = f"https://www.screener.in/company/{base_symbol}/consolidated/"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            text = soup.get_text(" ", strip=True)
            result = {}
            mcap_match = re.search(r"Market Cap\s*₹?\s*([\d,.]+)\s*Cr", text, re.I)
            pe_match = re.search(r"Stock P/E\s*([\d,.]+)", text, re.I)
            if mcap_match:
                result["marketCap"] = _parse_market_cap(f"{mcap_match.group(1)} Cr")
            if pe_match:
                result["trailingPE"] = _parse_number(pe_match.group(1))
            return result or None
        except Exception as exc:
            logger.warning("Screener fundamentals fallback failed for %s: %s", symbol, exc)
            return None

    @staticmethod
    def _load_fundamentals_cache() -> dict:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding="utf-8") as f:
                try:
                    cache = json.load(f)
                    return cache if isinstance(cache, dict) else {}
                except json.JSONDecodeError:
                    return {}
        return {}

    @staticmethod
    def _save_fundamentals_cache(cache: dict) -> None:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w', encoding="utf-8") as f:
            json.dump(cache, f)

    @staticmethod
    def get_fundamentals_with_fallback(symbol: str) -> dict | None:
        cache = RiskAndQualityAnalyzer._load_fundamentals_cache()
        cached_data = cache.get(symbol)
        if isinstance(cached_data, dict):
            try:
                last_fetched = datetime.datetime.fromisoformat(cached_data["timestamp"]).date()
                if (datetime.date.today() - last_fetched).days < CACHE_EXPIRY_DAYS:
                    info = cached_data.get("info")
                    if isinstance(info, dict):
                        return info
            except Exception:
                pass

        ticker = None
        info: dict | None = None
        try:
            ticker = get_ticker(symbol)
            info = get_info(symbol, ticker=ticker)
            if not info:
                raise ValueError("yfinance returned empty info dict")
        except Exception as exc:
            logger.info("yfinance info failed for %s: %s", symbol, exc)
            try:
                fast_info = get_fast_info(symbol, ticker=ticker)
                mcap = fast_info.get('marketCap') or fast_info.get("market_cap")
                info = {'marketCap': mcap, 'trailingPE': None, 'debtToEquity': None} if mcap else None
            except Exception:
                info = None

        if not info:
            for fallback in (
                RiskAndQualityAnalyzer.get_fundamentals_from_google_finance,
                RiskAndQualityAnalyzer.get_fundamentals_from_nse,
                RiskAndQualityAnalyzer.get_fundamentals_from_screener,
            ):
                info = fallback(symbol)
                if info:
                    break

        if info:
            cache[symbol] = {
                'info': info,
                'timestamp': datetime.datetime.now().isoformat(),
            }
            RiskAndQualityAnalyzer._save_fundamentals_cache(cache)
        return info

    @staticmethod
    def fundamentals_pass_quality(symbol: str, info: dict | None, settings_obj) -> bool:
        if not info:
            logger.warning(f"Could not process fundamentals for {symbol}: 'info' is empty or None after fallback.")
            return True

        mcap = info.get('marketCap', 0)
        if mcap is None:
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

    @staticmethod
    def relative_liquidity_check(df: pd.DataFrame, settings_obj) -> tuple[bool, str | None]:
        """
        Relative Liquidity Check: 10D Median Turnover vs 180D Median Turnover.
        A stock's recent liquidity should not be abnormally low compared to its history.
        This check helps filter out stocks with liquidity and volume anomalies.
        """
        history_window = min(len(df), 180)
        if history_window < 60:
            return False, f"Insufficient history for liquidity check ({len(df)} rows < 60)"
        
        turnover = df['Close'] * df['Volume']
        median_turnover_10d = turnover.tail(10).median()
        median_turnover_180d = turnover.tail(history_window).median()

        if median_turnover_180d == 0: return False, "Zero median turnover in last 180 days"

        if (median_turnover_10d / median_turnover_180d) < settings_obj.RELATIVE_LIQUIDITY_FACTOR:
            return False, (
                "Relative liquidity failure "
                f"({median_turnover_10d:.2f} vs {median_turnover_180d:.2f}, history_window={history_window})"
            )
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
    def relative_strength_check(
        df: pd.DataFrame,
        nifty_df: pd.DataFrame,
        settings_obj,
    ) -> tuple[bool, str | None]:
        if not settings_obj.RS_FILTER_ENABLED:
            return True, None
        lookback = settings_obj.RS_LOOKBACK_DAYS
        if df is None or df.empty or nifty_df is None or nifty_df.empty:
            return True, None
        if len(df) < lookback or len(nifty_df) < lookback:
            return True, None

        try:
            stock_close = pd.to_numeric(df["Close"], errors="coerce").dropna()
            nifty_close = pd.to_numeric(nifty_df["Close"], errors="coerce").dropna()
            if len(stock_close) < lookback or len(nifty_close) < lookback:
                return True, None
            stock_return = (float(stock_close.iloc[-1]) / float(stock_close.iloc[-lookback])) - 1
            nifty_return = (float(nifty_close.iloc[-1]) / float(nifty_close.iloc[-lookback])) - 1
            outperformance = (stock_return - nifty_return) * 100
        except Exception as exc:
            logger.warning("Relative strength check failed. Failing open. error=%s", exc)
            return True, None

        min_outperformance = float(getattr(settings_obj, "RS_MIN_OUTPERFORMANCE_PCT", 3.0))
        if outperformance >= min_outperformance:
            return True, None
        return (
            False,
            f"Weak relative strength; RS fail: stock {stock_return:.1%} vs Nifty {nifty_return:.1%} "
            f"(gap={outperformance:.1f}%)",
        )
    
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
        info = RiskAndQualityAnalyzer.get_fundamentals_with_fallback(symbol)
        return RiskAndQualityAnalyzer.fundamentals_pass_quality(symbol, info, settings_obj)

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
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        sector: str | None = None,
        cap_band: str | None = None,
        position_shares: int | None = None,
        position_value: float | None = None,
        position_size_pct: float | None = None,
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
        stock.stop_loss_price = stop_loss_price
        stock.take_profit_price = take_profit_price
        if stop_loss_pct is not None:
            stock.stop_loss_pct = stop_loss_pct
        if take_profit_pct is not None:
            stock.take_profit_pct = take_profit_pct
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
        if sector is not None:
            stock.sector = sector
        if cap_band is not None:
            stock.cap_band = cap_band
        if position_shares is not None:
            stock.position_shares = position_shares
        if position_value is not None:
            stock.position_value = position_value
        if position_size_pct is not None:
            stock.position_size_pct = position_size_pct
        logger.info(
            "RANKING_UPDATE: SET %s last_seen_date=%s rank=%s price=%.2f.",
            symbol,
            stock.last_seen_date,
            stock.rank_score,
            price,
        )
        return True

    def decay_unseen_ranks(self, seen_symbols: set[str]):
        logger.info(f"Decaying ranks for all stocks not in today's seen list ({len(seen_symbols)} symbols)...")
        try:
            stmt = select(MomentumStock)
            if seen_symbols:
                stmt = stmt.filter(MomentumStock.symbol.notin_(seen_symbols))
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


class MarketRegimeChecker:
    @staticmethod
    def is_bull_market(settings_obj) -> bool:
        today = datetime.datetime.now(zoneinfo.ZoneInfo(settings_obj.TIMEZONE)).date()
        if not settings_obj.MARKET_REGIME_FILTER_ENABLED:
            return True
        regime_cache = _get_regime_cache()
        if today in regime_cache:
            return regime_cache[today]

        index_symbol = getattr(settings_obj, "MARKET_REGIME_INDEX", "^NSEI")
        try:
            df = download_history(index_symbol, period="1y", interval="1d", auto_adjust=True, timeout=10)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.loc[:, ~df.columns.duplicated()]
            df = StockFetcher._normalize_market_dataframe(df, settings_obj)
            if df.empty or "Close" not in df.columns or len(df) < 200:
                logger.warning("MARKET REGIME: insufficient %s data; failing open.", index_symbol)
                regime_cache[today] = True
                return True

            close_series = pd.to_numeric(df["Close"], errors="coerce").dropna()
            if len(close_series) < 200:
                logger.warning("MARKET REGIME: insufficient clean %s close data; failing open.", index_symbol)
                regime_cache[today] = True
                return True

            latest_close = float(close_series.iloc[-1])
            sma_200 = float(close_series.tail(200).mean())
            is_bull = latest_close > sma_200
            logger.info(
                "MARKET REGIME: %s close=%.2f sma200=%.2f bull=%s",
                index_symbol,
                latest_close,
                sma_200,
                is_bull,
            )
            regime_cache[today] = is_bull
            return is_bull
        except Exception as exc:
            logger.warning("MARKET REGIME: check failed for %s: %s. Failing open.", index_symbol, exc)
            regime_cache[today] = True
            return True


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
        sector_counts: dict[str, int] = {}
        small_cap_count = 0
        
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

            if getattr(settings_obj, "DIVERSIFICATION_ENABLED", True):
                sector = stock.sector or "UNKNOWN"
                max_per_sector = max(1, int(getattr(settings_obj, "MAX_STOCKS_PER_SECTOR", 2)))
                if sector_counts.get(sector, 0) >= max_per_sector:
                    logger.info(f"DIVERSIFICATION: Skipping {stock.symbol}; sector limit reached for {sector}.")
                    continue
                if stock.cap_band == "SMALL_CAP" and small_cap_count >= getattr(settings_obj, "MAX_SMALL_CAP_TOP_PICKS", 3):
                    logger.info(f"DIVERSIFICATION: Skipping {stock.symbol}; small-cap limit reached.")
                    continue

            if stock.position_value:
                can_add, reason = PositionSizer.can_add_position(
                    session,
                    settings_obj.PORTFOLIO_CAPITAL,
                    stock.position_value,
                    settings_obj,
                )
                if not can_add:
                    logger.info("POSITION SIZING: Skipping %s: %s", stock.symbol, reason)
                    continue

            top_10_list.append(stock)
            sector_counts[stock.sector or "UNKNOWN"] = sector_counts.get(stock.sector or "UNKNOWN", 0) + 1
            if stock.cap_band == "SMALL_CAP":
                small_cap_count += 1

        for stock in top_10_list:
            stock.last_top10_date = today
            stock.top10_hit_count = (stock.top10_hit_count or 0) + 1
            if stock.entry_date is None or stock.exit_date is not None:
                stock.entry_date = today
                stock.entry_price = stock.current_price
                stock.high_water_mark = stock.current_price
                stock.trailing_stop_price = (
                    stock.current_price * (1 - settings_obj.TRAILING_STOP_PCT / 100)
                    if stock.current_price is not None
                    else None
                )
                stock.exit_date = None
                stock.exit_price = None
                stock.exit_reason = None
                stock.realized_return_pct = None
        
        session.commit()
        
        return top_10_list

    @staticmethod
    def _normalize_market_dataframe(df: pd.DataFrame, settings_obj) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        normalized_df = df.copy()
        index = pd.to_datetime(normalized_df.index, errors="coerce")
        valid_mask = ~pd.isna(index)
        normalized_df = normalized_df.loc[valid_mask].copy()
        index = pd.DatetimeIndex(index[valid_mask])

        if normalized_df.empty:
            return normalized_df

        market_tz = zoneinfo.ZoneInfo(settings_obj.TIMEZONE)
        if index.tz is not None:
            index = index.tz_convert(market_tz).tz_localize(None)

        normalized_df.index = index.normalize()
        normalized_df = normalized_df.loc[:, ~normalized_df.columns.duplicated()]
        normalized_df = normalized_df[~normalized_df.index.duplicated(keep="last")]
        return normalized_df.sort_index()

    @staticmethod
    def _extract_trade_date_from_bhavcopy(bhavcopy_df: pd.DataFrame, settings_obj) -> date | None:
        if bhavcopy_df is None or bhavcopy_df.empty or "BizDt" not in bhavcopy_df.columns:
            return None

        biz_dates = pd.to_datetime(bhavcopy_df["BizDt"], errors="coerce").dropna()
        if biz_dates.empty:
            return None
        return MarketValidator.coerce_to_market_date(biz_dates.max(), settings_obj)

    @staticmethod
    def _merge_market_data(
        symbol: str,
        df_yf: pd.DataFrame,
        bhavcopy_df: pd.DataFrame,
        settings_obj,
    ) -> tuple[pd.DataFrame, dict[str, str | int | None]]:
        normalized_yf = StockFetcher._normalize_market_dataframe(df_yf, settings_obj)
        yf_last_date = (
            MarketValidator.coerce_to_market_date(normalized_yf.index[-1], settings_obj)
            if not normalized_yf.empty
            else None
        )

        merge_info: dict[str, str | int | None] = {
            "source": "yfinance_only",
            "yf_last_date": str(yf_last_date) if yf_last_date else None,
            "bhavcopy_date": None,
            "final_last_date": str(yf_last_date) if yf_last_date else None,
            "row_count": len(normalized_yf),
        }

        if bhavcopy_df is None or bhavcopy_df.empty:
            return normalized_yf, merge_info

        symbol_without_suffix = symbol.split(".")[0]
        daily_data_row = bhavcopy_df[bhavcopy_df["TckrSymb"] == symbol_without_suffix]
        if daily_data_row.empty:
            merge_info["source"] = "yfinance_only_bhavcopy_miss"
            return normalized_yf, merge_info

        daily_data = daily_data_row.iloc[0]
        bhavcopy_timestamp = pd.to_datetime(daily_data["BizDt"], errors="coerce")
        bhavcopy_date = MarketValidator.coerce_to_market_date(bhavcopy_timestamp, settings_obj)
        merge_info["bhavcopy_date"] = str(bhavcopy_date) if bhavcopy_date else None

        if bhavcopy_date is None:
            merge_info["source"] = "yfinance_only_invalid_bhavcopy_date"
            return normalized_yf, merge_info

        bhavcopy_row = pd.DataFrame(
            {
                "Open": [daily_data["OpnPric"]],
                "High": [daily_data["HghPric"]],
                "Low": [daily_data["LwPric"]],
                "Close": [daily_data["ClsPric"]],
                "Volume": [daily_data["TtlTradgVol"]],
            },
            index=[pd.Timestamp(bhavcopy_date)],
        )

        merged_df = pd.concat([normalized_yf, bhavcopy_row], sort=False)
        merged_df = StockFetcher._normalize_market_dataframe(merged_df, settings_obj)
        final_last_date = (
            MarketValidator.coerce_to_market_date(merged_df.index[-1], settings_obj)
            if not merged_df.empty
            else None
        )

        if normalized_yf.empty:
            merge_source = "bhavcopy_only"
        elif yf_last_date == bhavcopy_date:
            merge_source = "bhavcopy_replaced_same_day_row"
        elif yf_last_date and yf_last_date < bhavcopy_date:
            merge_source = "bhavcopy_extended_yfinance"
        else:
            merge_source = "yfinance_plus_bhavcopy"

        merge_info.update(
            {
                "source": merge_source,
                "final_last_date": str(final_last_date) if final_last_date else None,
                "row_count": len(merged_df),
            }
        )
        return merged_df, merge_info
                            
    @staticmethod
    def process_single_batch(
        batch_tickers: list[str],
        batch_id: int,
        settings_obj,
        bhavcopy_df: pd.DataFrame,
        expected_market_date: date | None = None,
        nifty_df: pd.DataFrame | None = None,
        is_bull: bool = True,
    ) -> set[str]:
        logger.info(f"--- Starting Batch {batch_id} ---")
        qualified_symbols = set()
        min_history_days = max(30, int(getattr(settings_obj, "MIN_HISTORY_DAYS", 150)))
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
                        df_yf = download_history(symbol, period="1y", auto_adjust=True, timeout=10)
                        
                        # Flatten MultiIndex columns if present (fix for yfinance returning (Price, Ticker) columns)
                        if isinstance(df_yf.columns, pd.MultiIndex):
                            df_yf.columns = df_yf.columns.get_level_values(0)
                        
                        # FIX: Remove duplicate columns (caused by flattening MultiIndex sometimes)
                        df_yf = df_yf.loc[:, ~df_yf.columns.duplicated()]
                        
                        # FIX: Remove duplicate index dates (clean up yfinance data)
                        df_yf = df_yf[~df_yf.index.duplicated(keep='last')]

                        df, merge_info = StockFetcher._merge_market_data(symbol, df_yf, bhavcopy_df, settings_obj)
                        logger.info(
                            "DATA MERGE %s: source=%s yf_last_date=%s bhavcopy_date=%s final_last_date=%s rows=%s expected_market_date=%s",
                            symbol,
                            merge_info["source"],
                            merge_info["yf_last_date"],
                            merge_info["bhavcopy_date"],
                            merge_info["final_last_date"],
                            merge_info["row_count"],
                            expected_market_date,
                        )

                        if df.empty:
                            logger.info(
                                "SKIP %s: No data available after merge. source=%s yf_last_date=%s bhavcopy_date=%s",
                                symbol,
                                merge_info["source"],
                                merge_info["yf_last_date"],
                                merge_info["bhavcopy_date"],
                            )
                            continue
                        
                        if len(df) < min_history_days:
                            logger.info(
                                "SKIP %s: Insufficient data (%s rows < MIN_HISTORY_DAYS=%s). final_last_date=%s source=%s",
                                symbol,
                                len(df),
                                min_history_days,
                                merge_info["final_last_date"],
                                merge_info["source"],
                            )
                            continue

                        if not MarketValidator.validate_market_data_freshness(
                            df,
                            settings_obj,
                            symbol=symbol,
                            expected_market_date=expected_market_date,
                        ):
                            continue

                        current_close = float(df['Close'].iloc[-1])
                        high_52 = float(df['High'].max())
                        
                        if current_close < settings_obj.MIN_PRICE:
                            logger.info(f"SKIP {symbol}: Price ({current_close:.2f}) < MIN_PRICE ({settings_obj.MIN_PRICE}).")
                            continue

                        if current_close < (high_52 * settings_obj.NEAR_52_WEEK_HIGH_THRESHOLD):
                            threshold_price = high_52 * settings_obj.NEAR_52_WEEK_HIGH_THRESHOLD
                            logger.info(
                                "SKIP %s: Price %.2f below near-52-week-high threshold %.2f (high_52=%.2f, multiplier=%.2f).",
                                symbol,
                                current_close,
                                threshold_price,
                                high_52,
                                settings_obj.NEAR_52_WEEK_HIGH_THRESHOLD,
                            )
                            continue

                        is_liquid, liq_reason = RiskAndQualityAnalyzer.relative_liquidity_check(df, settings_obj)
                        if not is_liquid:
                            logger.info(f"SKIP {symbol}: {liq_reason}")
                            continue

                        is_confirmed, vol_reason = RiskAndQualityAnalyzer.volume_confirmation(df, settings_obj)
                        if not is_confirmed:
                            logger.info(f"SKIP {symbol}: {vol_reason}")
                            continue

                        if getattr(settings_obj, "RS_FILTER_ENABLED", True):
                            is_rs_ok, rs_reason = RiskAndQualityAnalyzer.relative_strength_check(
                                df, nifty_df, settings_obj
                            )
                            if not is_rs_ok:
                                logger.info("SKIP %s: %s", symbol, rs_reason)
                                continue

                        if getattr(settings_obj, "EARNINGS_EXCLUSION_ENABLED", True):
                            is_near_earnings, earnings_reason = EarningsCalendar.is_near_earnings(
                                symbol, engine_svc.today, settings_obj
                            )
                            if is_near_earnings:
                                logger.info("SKIP %s: %s", symbol, earnings_reason)
                                continue
	                            
                        fundamentals_info = None
                        if getattr(settings_obj, "FUNDAMENTAL_CHECK_ENABLED", True):
                            fundamentals_info = RiskAndQualityAnalyzer.get_fundamentals_with_fallback(symbol)
                            is_fundamental_ok = RiskAndQualityAnalyzer.fundamentals_pass_quality(
                                symbol, fundamentals_info, settings_obj
                            )
                        else:
                            is_fundamental_ok = True
                        if not is_fundamental_ok:
                            continue

                        risk_score, risk_reasons = RiskAndQualityAnalyzer.calculate_risk_score(df, current_close, high_52)
                        max_risk_score = 3 if is_bull else 2
                        if risk_score > max_risk_score:
                            logger.info(
                                "SKIP %s: Risk score %s exceeds %s threshold %s.",
                                symbol,
                                risk_score,
                                "bull" if is_bull else "bear/sideways",
                                max_risk_score,
                            )
                            continue
                        logger.info(f"QUALIFIED: {symbol} | Price: {current_close:.2f} | Risk: {risk_score} ({', '.join(risk_reasons)})")
                        
                        company_name = None
                        try:
                            company_name = get_company_name(symbol)
                        except Exception as company_name_exc:
                            logger.warning("Company name lookup failed for %s: %s", symbol, company_name_exc)
                        
                        high_date_idx = df['High'].idxmax()
                        high_date = high_date_idx.date() if isinstance(high_date_idx, pd.Timestamp) else high_date_idx
                        
                        low_date_idx = df['Low'].idxmin()
                        low_date = low_date_idx.date() if isinstance(low_date_idx, pd.Timestamp) else low_date_idx

                        stop_loss_pct = -abs(float(getattr(settings_obj, "STOP_LOSS_PCT", -8.0)))
                        take_profit_pct = abs(float(getattr(settings_obj, "TAKE_PROFIT_PCT", 15.0)))
                        stop_loss_price = current_close * (1 - abs(stop_loss_pct) / 100)
                        take_profit_price = current_close * (1 + take_profit_pct / 100)
                        market_cap = fundamentals_info.get("marketCap") if isinstance(fundamentals_info, dict) else None
                        sector = None
                        if isinstance(fundamentals_info, dict):
                            sector = fundamentals_info.get("sector") or fundamentals_info.get("industry")
                        position = PositionSizer.calculate_position(
                            settings_obj.PORTFOLIO_CAPITAL,
                            current_close,
                            stop_loss_price,
                            settings_obj,
                        )

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
                            stop_loss_price=stop_loss_price,
                            take_profit_price=take_profit_price,
                            stop_loss_pct=stop_loss_pct,
                            take_profit_pct=take_profit_pct,
                            sector=sector,
                            cap_band=_cap_band(market_cap),
                            position_shares=position["shares"] if position else None,
                            position_value=position["position_value"] if position else None,
                            position_size_pct=position["position_pct"] if position else None,
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
    def _get_relative_strength_benchmark(settings_obj) -> pd.DataFrame:
        today = datetime.datetime.now(zoneinfo.ZoneInfo(settings_obj.TIMEZONE)).date()
        cached = _NIFTY_RS_CACHE.get(today)
        if cached is not None:
            return cached

        try:
            nifty_df = download_history(
                settings_obj.MARKET_REGIME_INDEX,
                period="60d",
                interval="1d",
                auto_adjust=True,
                timeout=10,
            )
            if isinstance(nifty_df.columns, pd.MultiIndex):
                nifty_df.columns = nifty_df.columns.get_level_values(0)
            nifty_df = nifty_df.loc[:, ~nifty_df.columns.duplicated()]
            nifty_df = StockFetcher._normalize_market_dataframe(nifty_df, settings_obj)
            _NIFTY_RS_CACHE[today] = nifty_df
            return nifty_df
        except Exception as exc:
            logger.warning("Relative strength benchmark fetch failed: %s. Failing open.", exc)
            return pd.DataFrame()

    @staticmethod
    def scan_stocks_parallel(tickers: list[str], batch_size: int = 100, max_workers: int = 10):
        
        # --- Deduplicate tickers ---
        tickers = list(dict.fromkeys(tickers))

        bhavcopy_df = Bhavcopy.get_bhavcopy_data()
        current_settings = get_settings()
        is_bull = MarketRegimeChecker.is_bull_market(current_settings)
        logger.info(
            "MARKET REGIME: %s bull=%s. Risk threshold=%s.",
            current_settings.MARKET_REGIME_INDEX,
            is_bull,
            3 if is_bull else 2,
        )

        expected_market_date = StockFetcher._extract_trade_date_from_bhavcopy(bhavcopy_df, current_settings)
        if expected_market_date is None:
            expected_market_date = MarketValidator.get_expected_market_date(current_settings)

        nifty_df = (
            StockFetcher._get_relative_strength_benchmark(current_settings)
            if getattr(current_settings, "RS_FILTER_ENABLED", True)
            else pd.DataFrame()
        )
	        
        if bhavcopy_df.empty:
            logger.warning("Could not get Bhavcopy data. Proceeding with full universe as fallback.")
            filtered_tickers = tickers
        else:
            bhavcopy_symbols = set(bhavcopy_df['TckrSymb'].unique())
            logger.info(f"Loaded {len(bhavcopy_symbols)} unique symbols from Bhavcopy.")
            filtered_tickers = []
            filtered_out_tickers = []
            for ticker in tickers:
                if ticker.split(".")[0] in bhavcopy_symbols:
                    filtered_tickers.append(ticker)
                else:
                    filtered_out_tickers.append(ticker)
            for ticker in filtered_out_tickers:
                logger.info(
                    "SKIP %s: Filtered by Bhavcopy. Base symbol %s not present in latest Bhavcopy trade date %s.",
                    ticker,
                    ticker.split(".")[0],
                    expected_market_date,
                )
            logger.info(f"Universe filtered to {len(filtered_tickers)} actively traded stocks.")
        total = len(filtered_tickers)
        if total == 0:
            logger.warning(
                "No tickers to scan. Aborting. input_tickers=%s expected_market_date=%s bhavcopy_available=%s",
                len(tickers),
                expected_market_date,
                not bhavcopy_df.empty,
            )
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
        all_qualified_symbols = set()
        effective_workers = min(max_workers, len(batches))
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            future_to_batch = {
                executor.submit(
                    StockFetcher.process_single_batch,
                    batch,
                    i + 1,
                    current_settings,
                    bhavcopy_df,
                    expected_market_date,
                    nifty_df,
                    is_bull,
                ): i
                for i, batch in enumerate(batches)
            }
            for future in as_completed(future_to_batch):
                batch_num = future_to_batch[future] + 1
                try:
                    qualified_in_batch = future.result()
                    all_qualified_symbols.update(qualified_in_batch)
                    logger.info(f"Progress: Batch {batch_num}/{len(batches)} done. Found {len(qualified_in_batch)} qualified.")
                except Exception as exc:
                    logger.error(f'Batch {batch_num} generated an exception: {exc}', exc_info=True)
        if not all_qualified_symbols:
            logger.warning("No stocks qualified in this run. Running rank decay for all previously tracked symbols.")
        with get_db_context() as session:
            engine_svc = RankingEngine(session, current_settings)
            engine_svc.decay_unseen_ranks(all_qualified_symbols)
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
    def coerce_to_market_date(value, settings_obj) -> date | None:
        if value is None or pd.isna(value):
            return None

        timestamp = pd.Timestamp(value)
        market_tz = zoneinfo.ZoneInfo(settings_obj.TIMEZONE)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(market_tz).tz_localize(None)
        return timestamp.date()

    @staticmethod
    def get_expected_market_date(settings_obj) -> date:
        tz = zoneinfo.ZoneInfo(settings_obj.TIMEZONE)
        market_today = datetime.datetime.now(tz).date()
        try:
            latest_available_date = Bhavcopy.find_latest_available_date(
                market_today,
                settings_obj,
                max_lookback_days=7,
            )
            if latest_available_date is not None:
                return latest_available_date
        except Exception as exc:
            logger.warning(
                "Could not resolve latest available market date. Falling back to %s. error=%s",
                market_today,
                exc,
            )
        return market_today

    @staticmethod
    def validate_market_data_freshness(
        df: pd.DataFrame,
        settings_obj,
        symbol: str | None = None,
        expected_market_date: date | None = None,
    ) -> bool:
        if df.empty:
            logger.info("SKIP %s: Stale data check received an empty dataframe.", symbol or "<unknown>")
            return False

        tz = zoneinfo.ZoneInfo(settings_obj.TIMEZONE)
        market_today = datetime.datetime.now(tz).date()
        reference_date = expected_market_date or MarketValidator.get_expected_market_date(settings_obj)
        raw_last_index = df.index[-1]
        last_date = MarketValidator.coerce_to_market_date(raw_last_index, settings_obj)

        if last_date is None:
            logger.info(
                "SKIP %s: Stale data. market_today=%s expected_market_date=%s last_date=None raw_last_index=%s",
                symbol or "<unknown>",
                market_today,
                reference_date,
                raw_last_index,
            )
            return False

        delta = (reference_date - last_date).days
        if delta > 0:
            logger.info(
                "SKIP %s: Stale data. market_today=%s expected_market_date=%s last_date=%s raw_last_index=%s calendar_gap_from_today=%s.",
                symbol or "<unknown>",
                market_today,
                reference_date,
                last_date,
                raw_last_index,
                (market_today - last_date).days,
            )
            return False
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
