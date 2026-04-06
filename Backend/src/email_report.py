import logging
import smtplib
import ssl
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import pandas as pd
from sqlalchemy.orm import Session
from src.database import get_database_size, get_db_context
from src.models import MomentumStock
from src.config import get_settings
from src.yahoo_finance import download_history, get_fast_info, get_info, get_ticker
from src.services import RiskAndQualityAnalyzer
from sqlalchemy import select, desc, asc
import datetime
import os
from functools import lru_cache
import json

logger = logging.getLogger("Anveshq.EmailReport")


def _display_name(stock: MomentumStock) -> str:
    """Company name if available, else symbol."""
    raw_name = getattr(stock, "company_name", None)
    if not isinstance(raw_name, str):
        return stock.symbol
    cleaned = raw_name.strip()
    if not cleaned:
        return stock.symbol
    lowered = cleaned.lower()
    if lowered in {"none", "null", "nan"}:
        return stock.symbol
    return cleaned


def _google_search_url(symbol: str) -> str:
    """Google search URL for the stock (user can open for analysis)."""
    q = f"{symbol.replace('.NS', '').replace('.BO', '')} stock NSE"
    return f"https://www.google.com/search?q={urllib.parse.quote_plus(q)}"


def _format_inr(amount: float) -> str:
    """Format amount in Indian style (e.g. Rs. 1,08,390.73)."""
    s = f"{amount:,.2f}"
    int_str, _, dec = s.partition(".")
    int_str = int_str.replace(",", "")
    if len(int_str) <= 3:
        return f"Rs. {int_str}.{dec}"
    result = int_str[-3:]
    for i in range(len(int_str) - 3, 0, -2):
        start = max(0, i - 2)
        result = int_str[start:i] + "," + result
    return f"Rs. {result}.{dec}"


def _format_price(value: float | int | None) -> str:
    if isinstance(value, (int, float)):
        formatted = _format_inr(float(value))
        if formatted.endswith(".00"):
            return formatted[:-3]
        return formatted
    return "--"


def _format_date(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return "--"


def _format_signed_percent(value: float | None) -> str:
    if value is None:
        return "--"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


_fundamental_cache: dict[str, dict] = {}
_market_cache: dict[str, dict] = {}
_nse_quote_cache: dict[str, dict] = {}


def _parse_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        try:
            return float(cleaned)
        except Exception:
            return None
    return None


def _parse_market_cap_value(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip().upper()
    if not text:
        return None

    for token in ("RS.", "RS", "INR", "₹"):
        text = text.replace(token, "")
    text = text.replace(",", "").replace(" ", "")

    multiplier = 1.0
    if "CRORE" in text or text.endswith("CR") or "CR" in text:
        multiplier = 10_000_000
    elif "LAKH" in text or text.endswith("L") or "LAC" in text:
        multiplier = 100_000
    elif "TRILLION" in text or text.endswith("T"):
        multiplier = 1e12
    elif "BILLION" in text or text.endswith("B"):
        multiplier = 1e9
    elif "MILLION" in text or text.endswith("M"):
        multiplier = 1e6

    number_part = ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            number_part += ch
        elif number_part:
            break
    try:
        return float(number_part) * multiplier if number_part else None
    except Exception:
        return None


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result


@lru_cache(maxsize=1)
def _load_fundamentals_cache() -> dict:
    cache_path = os.path.join(os.path.dirname(__file__), "..", "fundamentals_cache.json")
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_cached_fundamentals(symbol: str) -> dict:
    cache = _load_fundamentals_cache()
    keys = [symbol]
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        keys.append(symbol.replace(".NS", "").replace(".BO", ""))
    else:
        keys.append(f"{symbol}.NS")
        keys.append(f"{symbol}.BO")
    for key in keys:
        entry = cache.get(key)
        if isinstance(entry, dict):
            info = entry.get("info")
            if isinstance(info, dict):
                return info
    return {}


def _combined_ma_ema_lines(
    price_above_20: bool | None,
    price_above_50: bool | None,
    price_above_ema20: bool | None,
    price_above_ema50: bool | None,
    ma_text: str,
    ema_text: str,
) -> list[str]:
    if all(
        value is not None
        for value in (price_above_20, price_above_50, price_above_ema20, price_above_ema50)
    ):
        if price_above_20 and price_above_50 and price_above_ema20 and price_above_ema50:
            return ["Price is trading above 20 and 50 day simple and exponential moving averages."]
        if (price_above_20 is False) and (price_above_50 is False) and (price_above_ema20 is False) and (price_above_ema50 is False):
            return ["Price is trading below 20 and 50 day simple and exponential moving averages."]
    lines = []
    if ma_text != "Simple moving average data is unavailable.":
        lines.append(ma_text)
    if ema_text != "Exponential moving average data is unavailable.":
        lines.append(ema_text)
    if not lines:
        lines.append("Moving average data is unavailable.")
    return lines


def _get_nse_quote(symbol: str) -> dict | None:
    if not symbol.endswith(".NS"):
        return None
    if symbol in _nse_quote_cache:
        return _nse_quote_cache[symbol]
    try:
        from nsetools import Nse
    except Exception:
        Nse = None

    try:
        if Nse is not None:
            nse = Nse()
            quote = nse.get_quote(symbol.replace(".NS", ""))
            if isinstance(quote, dict):
                _nse_quote_cache[symbol] = quote
                return quote
    except Exception:
        quote = None

    try:
        import requests
        session = requests.Session()
        base_url = "https://www.nseindia.com"
        symbol_clean = symbol.replace(".NS", "")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={symbol_clean}",
        }
        session.get(base_url, headers=headers, timeout=10)
        resp = session.get(f"{base_url}/api/quote-equity?symbol={symbol_clean}", headers=headers, timeout=10)
        if resp.ok:
            data = resp.json()
            if isinstance(data, dict):
                _nse_quote_cache[symbol] = data
                return data
    except Exception:
        return None
    return None


def _get_fundamentals(symbol: str, current_price: float | None = None) -> dict:
    if symbol in _fundamental_cache:
        return _fundamental_cache[symbol]
    ticker = None
    info = {}
    try:
        ticker = get_ticker(symbol)
        info = get_info(symbol, ticker=ticker)
    except Exception:
        info = {}

    market_cap = info.get("marketCap")
    pe_ratio = info.get("trailingPE") or info.get("forwardPE") or info.get("priceEpsCurrentYear")
    debt_to_equity = info.get("debtToEquity")
    shares_outstanding = info.get("sharesOutstanding") or info.get("shares")
    trailing_eps = info.get("trailingEps") or info.get("epsTrailingTwelveMonths") or info.get("epsCurrentYear")
    sector = info.get("sector") or info.get("industry") or info.get("industryDisp")

    fast_info = None
    if ticker is not None:
        try:
            fast_info = get_fast_info(symbol, ticker=ticker)
        except Exception:
            fast_info = None

    if market_cap is None and fast_info:
        try:
            market_cap = fast_info.get("marketCap") or fast_info.get("market_cap")
        except Exception:
            pass

    if fast_info:
        if market_cap is None:
            market_cap = fast_info.get("marketCap") or fast_info.get("market_cap")
        if pe_ratio is None:
            pe_ratio = fast_info.get("pe") or fast_info.get("pe_ratio") or fast_info.get("trailingPE")
        if shares_outstanding is None:
            shares_outstanding = fast_info.get("shares") or fast_info.get("sharesOutstanding")
        if trailing_eps is None:
            trailing_eps = fast_info.get("eps") or fast_info.get("trailingEps")

    cached_info = _get_cached_fundamentals(symbol)
    if cached_info:
        market_cap = market_cap or cached_info.get("marketCap")
        pe_ratio = pe_ratio or cached_info.get("trailingPE") or cached_info.get("forwardPE") or cached_info.get("priceEpsCurrentYear")
        debt_to_equity = debt_to_equity or cached_info.get("debtToEquity")
        shares_outstanding = shares_outstanding or cached_info.get("sharesOutstanding") or cached_info.get("floatShares")
        trailing_eps = trailing_eps or cached_info.get("trailingEps") or cached_info.get("epsTrailingTwelveMonths") or cached_info.get("epsCurrentYear")
        sector = sector or cached_info.get("sector") or cached_info.get("industry") or cached_info.get("industryDisp")

    if market_cap is None or pe_ratio is None:
        try:
            fallback = RiskAndQualityAnalyzer.get_fundamentals_from_google_finance(symbol)
            if fallback:
                market_cap = market_cap or fallback.get("marketCap")
                pe_ratio = pe_ratio or fallback.get("trailingPE")
        except Exception:
            pass

    if (market_cap is None or pe_ratio is None or debt_to_equity is None or not sector):
        try:
            direct_info = get_info(symbol)
            if isinstance(direct_info, dict):
                market_cap = market_cap or direct_info.get("marketCap")
                pe_ratio = pe_ratio or direct_info.get("trailingPE") or direct_info.get("forwardPE")
                debt_to_equity = debt_to_equity or direct_info.get("debtToEquity")
                sector = sector or direct_info.get("sector") or direct_info.get("industry")
        except Exception:
            pass

    if (market_cap is None or pe_ratio is None or debt_to_equity is None or not sector) and symbol.endswith(".NS"):
        quote = _get_nse_quote(symbol)
        if quote:
            info_block = quote.get("info") if isinstance(quote.get("info"), dict) else {}
            metadata_block = quote.get("metadata") if isinstance(quote.get("metadata"), dict) else {}
            price_info = quote.get("priceInfo") if isinstance(quote.get("priceInfo"), dict) else {}
            if market_cap is None:
                market_cap = _parse_market_cap_value(
                    quote.get("marketCapFull")
                    or quote.get("marketCap")
                    or quote.get("marketCapValue")
                    or quote.get("marketCapitalisation")
                    or metadata_block.get("marketCap")
                    or info_block.get("marketCap")
                )
            if pe_ratio is None:
                pe_ratio = _parse_number(
                    quote.get("pE")
                    or quote.get("pe")
                    or quote.get("priceEarnings")
                    or metadata_block.get("pE")
                    or metadata_block.get("pe")
                    or price_info.get("pE")
                    or price_info.get("pe")
                )
            if debt_to_equity is None:
                debt_to_equity = _parse_number(
                    quote.get("debtEquity")
                    or quote.get("debtToEquity")
                    or metadata_block.get("debtToEquity")
                    or info_block.get("debtToEquity")
                )
            if not sector:
                sector = (
                    quote.get("industry")
                    or quote.get("industryName")
                    or quote.get("sector")
                    or quote.get("sectorName")
                    or info_block.get("industry")
                    or info_block.get("sector")
                    or info_block.get("industryCategory")
                    or info_block.get("industryGroup")
                )

    if shares_outstanding is None and ticker is not None:
        try:
            if hasattr(ticker, "get_shares_full"):
                shares_df = ticker.get_shares_full()
                if shares_df is not None and not shares_df.empty:
                    shares_outstanding = float(shares_df.iloc[-1])
        except Exception:
            pass

    if trailing_eps is None and ticker is not None:
        try:
            income_stmt = getattr(ticker, "income_stmt", None)
            if income_stmt is None or income_stmt.empty:
                income_stmt = getattr(ticker, "financials", None)
            if income_stmt is not None and not income_stmt.empty:
                def _find_income(keys: list[str]) -> float | None:
                    for key in keys:
                        if key in income_stmt.index:
                            series = income_stmt.loc[key].dropna()
                            if not series.empty:
                                return float(series.iloc[0])
                    return None
                net_income = _find_income([
                    "Net Income",
                    "Net Income Common Stockholders",
                    "Net Income Applicable To Common Shares",
                    "Net Income Available to Common Shareholders",
                ])
                if net_income is not None and shares_outstanding:
                    trailing_eps = net_income / float(shares_outstanding)
        except Exception:
            pass

    if market_cap is None and current_price is not None and shares_outstanding:
        try:
            market_cap = float(current_price) * float(shares_outstanding)
        except Exception:
            pass

    if pe_ratio is None and current_price is not None and trailing_eps:
        try:
            eps_val = float(trailing_eps)
            if eps_val != 0:
                pe_ratio = float(current_price) / eps_val
        except Exception:
            pass

    if debt_to_equity is None and ticker is not None:
        try:
            balance_sheet = ticker.balance_sheet
            if balance_sheet is not None and not balance_sheet.empty:
                def _latest_value(keys: list[str]) -> float | None:
                    for key in keys:
                        if key in balance_sheet.index:
                            series = balance_sheet.loc[key].dropna()
                            if not series.empty:
                                return float(series.iloc[0])
                    return None

                total_liab = _latest_value([
                    "Total Liab",
                    "Total Liabilities Net Minority Interest",
                    "Total Liabilities",
                ])
                total_equity = _latest_value([
                    "Total Stockholder Equity",
                    "Total Equity Gross Minority Interest",
                    "Total Equity",
                ])
                if total_liab is not None and total_equity:
                    debt_to_equity = total_liab / total_equity
        except Exception:
            pass

    data = {
        "marketCap": market_cap,
        "trailingPE": pe_ratio,
        "debtToEquity": debt_to_equity,
        "sector": sector,
    }
    _fundamental_cache[symbol] = data
    return data


def _calculate_rsi(close_series: pd.Series, period: int = 14) -> float | None:
    if close_series is None or len(close_series) <= period:
        return None
    delta = close_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    value = rsi.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def _get_market_snapshot(symbol: str) -> dict:
    if symbol in _market_cache:
        return _market_cache[symbol]

    snapshot = {
        "current_price": None,
        "day_change_pct": None,
        "ma20": None,
        "ma50": None,
        "ema20": None,
        "ema50": None,
        "rsi": None,
        "volume": None,
        "avg_volume_20": None,
        "volume_vs_avg_pct": None,
        "support": None,
        "resistance": None,
        "high_52": None,
        "low_52": None,
        "high_52_date": None,
        "low_52_date": None,
    }

    try:
        df = download_history(symbol, period="1y", interval="1d", auto_adjust=False)
        if df is None or df.empty:
            _market_cache[symbol] = snapshot
            return snapshot

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()]
        df = df[~df.index.duplicated(keep="last")]

        close = df.get("Close")
        if close is None or close.empty:
            _market_cache[symbol] = snapshot
            return snapshot

        current_price = float(close.iloc[-1])
        snapshot["current_price"] = current_price

        if len(close) >= 2:
            prev_close = float(close.iloc[-2])
            if prev_close:
                snapshot["day_change_pct"] = ((current_price / prev_close) - 1) * 100

        if len(close) >= 20:
            snapshot["ma20"] = float(close.rolling(20).mean().iloc[-1])
        if len(close) >= 50:
            snapshot["ma50"] = float(close.rolling(50).mean().iloc[-1])
        if len(close) >= 20:
            snapshot["ema20"] = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        if len(close) >= 50:
            snapshot["ema50"] = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

        snapshot["rsi"] = _calculate_rsi(close, period=14)

        if "Volume" in df.columns:
            vol = df["Volume"].dropna()
            if not vol.empty:
                snapshot["volume"] = float(vol.iloc[-1])
                if len(vol) >= 20:
                    snapshot["avg_volume_20"] = float(vol.tail(20).mean())
                if snapshot["avg_volume_20"]:
                    snapshot["volume_vs_avg_pct"] = ((snapshot["volume"] / snapshot["avg_volume_20"]) - 1) * 100

        lows = df.get("Low")
        highs = df.get("High")
        if lows is not None and not lows.empty:
            snapshot["support"] = float(lows.tail(20).min())
        if highs is not None and not highs.empty:
            snapshot["resistance"] = float(highs.tail(20).max())

        if highs is not None and not highs.empty:
            high_value = float(highs.max())
            high_date = highs.idxmax()
            snapshot["high_52"] = high_value
            snapshot["high_52_date"] = high_date.date() if hasattr(high_date, "date") else high_date

        if lows is not None and not lows.empty:
            low_value = float(lows.min())
            low_date = lows.idxmin()
            snapshot["low_52"] = low_value
            snapshot["low_52_date"] = low_date.date() if hasattr(low_date, "date") else low_date
    except Exception:
        pass

    _market_cache[symbol] = snapshot
    return snapshot


def _format_percent(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.2f}%"


def _format_numeric(value: float | int | None) -> str:
    if value is None:
        return "--"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _exchange_label(symbol: str) -> str:
    if symbol.endswith(".NS"):
        return "NSE"
    if symbol.endswith(".BO"):
        return "BSE"
    return "NSE/BSE"


def _symbol_short(symbol: str) -> str:
    return symbol.replace(".NS", "").replace(".BO", "")


def _cap_band(market_cap: float | None) -> str:
    if market_cap is None:
        return "CAP DATA UNAVAILABLE"
    # Market cap is in rupees. Convert to crores for thresholds.
    cap_cr = market_cap / 10_000_000
    if cap_cr >= 20000:
        return "LARGE CAP"
    if cap_cr >= 5000:
        return "MID CAP"
    return "SMALL CAP"


def _format_market_cap(market_cap: float | None) -> str | None:
    if market_cap is None:
        return None
    try:
        cap_cr = float(market_cap) / 10_000_000
    except Exception:
        return None
    return f"Rs. {cap_cr:,.2f} Cr"


def _format_value_html(value: str | None, na_text: str = "--") -> str:
    if value is None or value == "--":
        return f'<div class="value data-na">{na_text}</div>'
    return f'<div class="value">{value}</div>'


def _derive_target_stoploss(current: float | None, resistance: float | None, support: float | None, high_52: float | None, low_52: float | None) -> tuple[float | None, float | None]:
    target = None
    stop = None

    if current is not None:
        if resistance is not None and resistance > current * 1.01:
            target = resistance
        elif high_52 is not None and high_52 > current * 1.01:
            target = high_52
        else:
            target = current * 1.05

        if support is not None and support < current * 0.99:
            stop = support
        elif low_52 is not None and low_52 < current * 0.99:
            stop = low_52
        else:
            stop = current * 0.95

    return target, stop


def _format_rr_ratio(current: float | None, target: float | None, stop: float | None) -> str:
    if current is None or target is None or stop is None:
        return "--"
    reward = target - current
    risk = current - stop
    if reward <= 0 or risk <= 0:
        return "--"
    ratio = reward / risk
    return f"1:{ratio:.2f}"


def _rsi_comment(rsi: float | None) -> str:
    if rsi is None:
        return "RSI data is unavailable."
    if rsi >= 60:
        return f"RSI is at {rsi:.1f}, indicating positive momentum."
    if rsi >= 45:
        return f"RSI is at {rsi:.1f}, indicating neutral momentum."
    return f"RSI is at {rsi:.1f}, indicating weak momentum."


def _build_top_pick_card_html(stock: MomentumStock) -> str:
    snapshot = _get_market_snapshot(stock.symbol)
    current_price = snapshot.get("current_price") or getattr(stock, "current_price", None)
    fundamentals = _get_fundamentals(stock.symbol, current_price=current_price)

    name = _display_name(stock)
    exchange = _exchange_label(stock.symbol)
    url = _google_search_url(stock.symbol)
    symbol_short = _symbol_short(stock.symbol)

    day_change = snapshot.get("day_change_pct")
    support = snapshot.get("support")
    resistance = snapshot.get("resistance")

    ma20 = snapshot.get("ma20")
    ma50 = snapshot.get("ma50")
    ema20 = snapshot.get("ema20")
    ema50 = snapshot.get("ema50")

    price_above_20 = current_price is not None and ma20 is not None and current_price > ma20
    price_above_50 = current_price is not None and ma50 is not None and current_price > ma50

    if price_above_20 and price_above_50:
        ma_text = "Price is trading above 20 and 50 day simple moving averages."
    elif price_above_20 and not price_above_50:
        ma_text = "Price is trading above the 20 day simple moving average but below the 50 day simple moving average."
    elif (price_above_20 is False) and (price_above_50 is False):
        ma_text = "Price is trading below 20 and 50 day simple moving averages."
    else:
        ma_text = "Simple moving average data is unavailable."

    price_above_ema20 = current_price is not None and ema20 is not None and current_price > ema20
    price_above_ema50 = current_price is not None and ema50 is not None and current_price > ema50
    if price_above_ema20 and price_above_ema50:
        ema_text = "Price is trading above 20 and 50 day exponential moving averages."
    elif price_above_ema20 and not price_above_ema50:
        ema_text = "Price is trading above the 20 day exponential moving average but below the 50 day exponential moving average."
    elif (price_above_ema20 is False) and (price_above_ema50 is False):
        ema_text = "Price is trading below 20 and 50 day exponential moving averages."
    else:
        ema_text = "Exponential moving average data is unavailable."

    volume_delta = snapshot.get("volume_vs_avg_pct")
    if volume_delta is not None:
        volume_text = f"Volume is {_format_signed_percent(volume_delta)} vs the 20 day average."
    else:
        volume_text = "Volume data is unavailable."

    rsi_text = _rsi_comment(snapshot.get("rsi"))
    support_text = f"Immediate support zone observed near {_format_price(support)}." if support else "Support data is unavailable."
    resistance_text = f"Near-term resistance zone observed around {_format_price(resistance)}." if resistance else "Resistance data is unavailable."

    pe_ratio = fundamentals.get("trailingPE")
    market_cap = fundamentals.get("marketCap")
    debt_to_equity = fundamentals.get("debtToEquity")
    market_cap_str = _format_market_cap(market_cap) or "--"

    high_52 = snapshot.get("high_52") or getattr(stock, "high_52_week_price", None)
    low_52 = snapshot.get("low_52") or getattr(stock, "low_52_week", None)
    high_52_date = snapshot.get("high_52_date") or getattr(stock, "high_52_week_date", None)
    low_52_date = snapshot.get("low_52_date") or getattr(stock, "low_52_week_date", None)
    high_52_date_str = _format_date(high_52_date)
    low_52_date_str = _format_date(low_52_date)
    high_52_date_html = f'<small style="color: #64748b;">on {high_52_date_str}</small>' if high_52_date_str != "--" else ""
    low_52_date_html = f'<small style="color: #64748b;">on {low_52_date_str}</small>' if low_52_date_str != "--" else ""

    sector = fundamentals.get("sector") or "Unknown Sector"
    sector_name = sector.split(" - ")[0].split("/")[0].strip() if isinstance(sector, str) else "Unknown Sector"
    if not sector_name:
        sector_name = "Unknown Sector"
    category = f"{sector_name} - {_cap_band(market_cap)}".upper()

    target_price, stop_loss = _derive_target_stoploss(current_price, resistance, support, high_52, low_52)
    rr_ratio = _format_rr_ratio(current_price, target_price, stop_loss)
    time_horizon = "3-6 months"
    rr_text = "Data not available"
    if rr_ratio != "--":
        rr_text = f"Approximately {rr_ratio} based on historical patterns"

    ma_ema_lines = _combined_ma_ema_lines(
        price_above_20, price_above_50, price_above_ema20, price_above_ema50, ma_text, ema_text
    )
    observation_points = _dedupe_lines(
        ma_ema_lines
        + [
            rsi_text,
            volume_text,
            support_text,
            resistance_text,
        ]
    )

    return f"""
      <div class="stock-card">
        <div class="stock-header">
          <h3 class="stock-name"><a href="{url}" target="_blank" rel="noopener">{name} ({symbol_short})</a></h3>
          <span class="stock-category">{category}</span>
        </div>

        <table role="presentation" class="metrics-table" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td class="metric-cell">
              <div class="metric-box cmp">
                <div class="metric-label">Current Level</div>
                <div class="metric-value">{_format_price(current_price)}</div>
              </div>
            </td>
            <td class="metric-cell">
              <div class="metric-box target">
                <div class="metric-label">Observed Target</div>
                <div class="metric-value">{_format_price(target_price)}</div>
              </div>
            </td>
            <td class="metric-cell">
              <div class="metric-box stop-loss">
                <div class="metric-label">Risk Level</div>
                <div class="metric-value">{_format_price(stop_loss)}</div>
              </div>
            </td>
          </tr>
        </table>

        <div class="analyst-section">
          <div class="analyst-label">Research Observations</div>
          <div class="analyst-content">
            <p>Based on our analysis of publicly available data, we've identified several factors worth monitoring:</p>
            <ul>
              {"".join(f"<li>{item}</li>" for item in observation_points[:6])}
            </ul>
          </div>
          <div class="info-box">
            <p><strong>Observation Period:</strong> {time_horizon} | <strong>Potential Risk-Reward:</strong> {rr_text}</p>
          </div>
        </div>
      </div>
    """

def _build_technical_card_html(stock: MomentumStock, roi_value: float | None = None) -> str:
    snapshot = _get_market_snapshot(stock.symbol)
    current_price = snapshot.get("current_price") or getattr(stock, "current_price", None)
    fundamentals = _get_fundamentals(stock.symbol, current_price=current_price)

    name = _display_name(stock)
    exchange = _exchange_label(stock.symbol)

    day_change = snapshot.get("day_change_pct")
    support = snapshot.get("support")
    resistance = snapshot.get("resistance")

    pe_ratio = fundamentals.get("trailingPE")
    market_cap = fundamentals.get("marketCap")
    market_cap_str = _format_market_cap(market_cap)

    high_52 = snapshot.get("high_52") or getattr(stock, "high_52_week_price", None)
    low_52 = snapshot.get("low_52") or getattr(stock, "low_52_week", None)
    high_52_date = snapshot.get("high_52_date") or getattr(stock, "high_52_week_date", None)
    low_52_date = snapshot.get("low_52_date") or getattr(stock, "low_52_week_date", None)
    high_52_date_str = _format_date(high_52_date)
    low_52_date_str = _format_date(low_52_date)
    high_52_date_html = f'<small style="color: #64748b;">on {high_52_date_str}</small>' if high_52_date_str != "--" else ""
    low_52_date_html = f'<small style="color: #64748b;">on {low_52_date_str}</small>' if low_52_date_str != "--" else ""

    ma20 = snapshot.get("ma20")
    ma50 = snapshot.get("ma50")
    ema20 = snapshot.get("ema20")
    ema50 = snapshot.get("ema50")

    price_above_20 = current_price is not None and ma20 is not None and current_price > ma20
    price_above_50 = current_price is not None and ma50 is not None and current_price > ma50

    if price_above_20 and price_above_50:
        ma_text = "Price is trading above 20 and 50 day simple moving averages."
    elif price_above_20 and not price_above_50:
        ma_text = "Price is trading above the 20 day simple moving average but below the 50 day simple moving average."
    elif (price_above_20 is False) and (price_above_50 is False):
        ma_text = "Price is trading below 20 and 50 day simple moving averages."
    else:
        ma_text = "Simple moving average data is unavailable."

    price_above_ema20 = current_price is not None and ema20 is not None and current_price > ema20
    price_above_ema50 = current_price is not None and ema50 is not None and current_price > ema50
    if price_above_ema20 and price_above_ema50:
        ema_text = "Price is trading above 20 and 50 day exponential moving averages."
    elif price_above_ema20 and not price_above_ema50:
        ema_text = "Price is trading above the 20 day exponential moving average but below the 50 day exponential moving average."
    elif (price_above_ema20 is False) and (price_above_ema50 is False):
        ema_text = "Price is trading below 20 and 50 day exponential moving averages."
    else:
        ema_text = "Exponential moving average data is unavailable."

    volume_delta = snapshot.get("volume_vs_avg_pct")
    if volume_delta is not None:
        volume_text = f"Volume is {_format_signed_percent(volume_delta)} vs the 20 day average."
    else:
        volume_text = "Volume data is unavailable."

    rsi_text = _rsi_comment(snapshot.get("rsi"))
    support_text = f"Immediate support zone observed near {_format_price(support)}." if support else "Support data is unavailable."
    resistance_text = f"Near-term resistance zone observed around {_format_price(resistance)}." if resistance else "Resistance data is unavailable."

    ma_signal = "signal-neutral"
    ma_label = "Mixed"
    if price_above_20 and price_above_50:
        ma_signal = "signal-bullish"
        ma_label = "Uptrend"
    elif (price_above_20 is False) and (price_above_50 is False):
        ma_signal = "signal-bearish"
        ma_label = "Downtrend"
    elif price_above_20 is None or price_above_50 is None:
        ma_signal = "signal-warning"
        ma_label = "Data Missing"

    ema_signal = "signal-neutral"
    ema_label = "Transition"
    if price_above_ema20 and price_above_ema50:
        ema_signal = "signal-bullish"
        ema_label = "Bullish"
    elif (price_above_ema20 is False) and (price_above_ema50 is False):
        ema_signal = "signal-bearish"
        ema_label = "Bearish"
    elif price_above_ema20 is None or price_above_ema50 is None:
        ema_signal = "signal-warning"
        ema_label = "Data Missing"

    rsi_value = snapshot.get("rsi")
    rsi_signal = "signal-neutral"
    rsi_label = "Neutral"
    if rsi_value is None:
        rsi_signal = "signal-warning"
        rsi_label = "Data Missing"
    elif rsi_value >= 60:
        rsi_signal = "signal-bullish"
        rsi_label = "Bullish"
    elif rsi_value < 45:
        rsi_signal = "signal-bearish"
        rsi_label = "Bearish"

    volume_signal = "signal-neutral"
    volume_label = "Neutral"
    if volume_delta is None:
        volume_signal = "signal-warning"
        volume_label = "Data Missing"
    elif volume_delta >= 0:
        volume_signal = "signal-bullish"
        volume_label = "Strong Interest"
    else:
        volume_signal = "signal-warning"
        volume_label = "Low Conviction"

    summary_signal = "mixed technical signals"
    if rsi_value is not None and price_above_20 and price_above_50:
        summary_signal = "multiple bullish technical indicators"
    elif rsi_value is not None and (price_above_20 is False) and (price_above_50 is False):
        summary_signal = "bearish technical signals"

    ma_ema_items: list[tuple[str, str, str]] = []
    if all(
        value is not None
        for value in (price_above_20, price_above_50, price_above_ema20, price_above_ema50)
    ):
        if price_above_20 and price_above_50 and price_above_ema20 and price_above_ema50:
            ma_ema_items = [
                ("Price is trading above 20 and 50 day simple and exponential moving averages.", "signal-bullish", "Uptrend")
            ]
        elif (price_above_20 is False) and (price_above_50 is False) and (price_above_ema20 is False) and (price_above_ema50 is False):
            ma_ema_items = [
                ("Price is trading below 20 and 50 day simple and exponential moving averages.", "signal-bearish", "Downtrend")
            ]

    if not ma_ema_items:
        if ma_text != "Simple moving average data is unavailable.":
            ma_ema_items.append((ma_text, ma_signal, ma_label))
        if ema_text != "Exponential moving average data is unavailable.":
            ma_ema_items.append((ema_text, ema_signal, ema_label))
        if not ma_ema_items:
            ma_ema_items = [("Moving average data is unavailable.", "signal-warning", "Data Missing")]

    if day_change is None:
        day_change_html = _format_value_html(_format_signed_percent(day_change))
    else:
        day_class = "price-change-positive" if day_change >= 0 else "price-change-negative"
        day_change_html = f'<div class="value {day_class}">{_format_signed_percent(day_change)}</div>'

    return f"""
      <div class="technical-card">
        <div class="technical-header">
          <h3 class="technical-title">{name}</h3>
          <span class="technical-exchange">{exchange}</span>
        </div>

        <table role="presentation" class="price-info-table" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td class="price-info-cell">
              <div class="price-info-item">
                <strong>Last Traded Price</strong>
                {_format_value_html(_format_price(current_price))}
              </div>
            </td>
            <td class="price-info-cell">
              <div class="price-info-item">
                <strong>Daily Change</strong>
                {day_change_html}
              </div>
            </td>
          </tr>
          <tr>
            <td class="price-info-cell">
              <div class="price-info-item">
                <strong>52-Week High</strong>
                {_format_value_html(_format_price(high_52))}
                {high_52_date_html}
              </div>
            </td>
            <td class="price-info-cell">
              <div class="price-info-item">
                <strong>52-Week Low</strong>
                {_format_value_html(_format_price(low_52))}
                {low_52_date_html}
              </div>
            </td>
          </tr>
          <tr>
            <td class="price-info-cell">
              <div class="price-info-item">
                <strong>P/E Ratio</strong>
                {_format_value_html(_format_numeric(pe_ratio))}
              </div>
            </td>
            <td class="price-info-cell">
              <div class="price-info-item">
                <strong>Market Cap</strong>
                {_format_value_html(market_cap_str)}
              </div>
            </td>
          </tr>
        </table>

        <div class="technical-section">
          <div class="technical-section-title">Technical Indicators to Study</div>
          <ul class="technical-observations">
            {"".join(f'<li>{item} <span class="signal-badge {sig}">{label}</span></li>' for item, sig, label in ma_ema_items)}
            <li>{rsi_text} <span class="signal-badge {rsi_signal}">{rsi_label}</span></li>
            <li>{volume_text} <span class="signal-badge {volume_signal}">{volume_label}</span></li>
          </ul>
        </div>

        <div class="key-levels">
          <div class="key-levels-title">Key Price Levels to Monitor</div>
          <div class="key-levels-grid">
            <div class="key-level-item">
              <strong>Support Zone</strong>
              <span class="level-value">{_format_price(support)}</span>
            </div>
            <div class="key-level-item">
              <strong>Resistance Zone</strong>
              <span class="level-value">{_format_price(resistance)}</span>
            </div>
          </div>
        </div>

        <div class="educational-note">
          <div class="educational-note-title">What This Means</div>
          <p class="educational-note-content">
            The stock shows <strong>{summary_signal}</strong>. Use these signals as a learning reference and verify with your own analysis. Always manage risk appropriately.
          </p>
        </div>
      </div>
    """

# --- 1. DATA ENGINE ---
def get_top_picks(session: Session, limit: int = 5) -> list[MomentumStock]:
    """
    Fetches the top momentum stocks based on rank and recent activity.
    """
    stmt = select(MomentumStock).order_by(
        desc(MomentumStock.rank_score),
        desc(MomentumStock.daily_rank_delta)
    ).limit(limit)
    return session.execute(stmt).scalars().all()

def get_missed_opportunities(session: Session, exclude_symbols: set[str], limit: int = 5) -> list[MomentumStock]:
    """
    Finds stocks with strong recent moves in the past week that are not in top picks.
    """
    one_week_ago = datetime.date.today() - datetime.timedelta(days=7)
    stmt = select(MomentumStock).filter(MomentumStock.last_seen_date >= one_week_ago).order_by(
        desc(MomentumStock.daily_rank_delta),
        desc(MomentumStock.rank_score)
    ).limit(50)

    candidates = session.execute(stmt).scalars().all()
    results: list[MomentumStock] = []
    for stock in candidates:
        if stock.symbol in exclude_symbols:
            continue
        results.append(stock)
        if len(results) >= limit:
            break
    return results

def calculate_roi(symbol: str) -> float | None:
    """
    Calculates the ROI for a stock over the last week.
    (Monday Open vs Friday Close)
    """
    today = datetime.date.today()
    last_monday = today - datetime.timedelta(days=today.weekday())
    last_friday = last_monday + datetime.timedelta(days=4)
    
    try:
        df = download_history(
            symbol,
            start=last_monday,
            end=last_friday + datetime.timedelta(days=1),
            auto_adjust=False,
        )
        if len(df) < 2:
            return None
        # Flatten MultiIndex columns if present (yfinance can return Series for single column)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        monday_open = df["Open"].iloc[0]
        friday_close = df["Close"].iloc[-1]
        # Ensure scalars (yfinance may return Series in some cases)
        if hasattr(monday_open, "squeeze"):
            monday_open = monday_open.squeeze()
        if hasattr(friday_close, "squeeze"):
            friday_close = friday_close.squeeze()
        roi = ((float(friday_close) - float(monday_open)) / float(monday_open)) * 100
        return roi
    except Exception:
        return None

# --- 2. EMAIL CONTENT BUILDER ---

def generate_email_html(top_picks: list[MomentumStock], missed_opportunities: list[MomentumStock], roi_map: dict[str, float | None]) -> str:
    """
    Builds the HTML content for the weekly email report (no graphs).
    Uses company name when available, current price in Rs., and Google search links.
    """

    top_cards = "\n".join(_build_top_pick_card_html(stock) for stock in top_picks)
    watchlist_section = ""
    if top_cards:
        watchlist_section = f"""
        <div class="section">
          <h2 class="section-header">
            Stocks on Our Research Watchlist
            <span class="educational-badge">For Educational Purposes</span>
          </h2>
          {top_cards}
        </div>
        """

    technical_cards = ""
    if missed_opportunities:
        technical_cards = "\n".join(
            _build_technical_card_html(stock, roi_value=roi_map.get(stock.symbol))
            for stock in missed_opportunities
        )
    else:
        technical_cards = '<p class="data-na">No patterns met the screening criteria this week. We will continue monitoring and share new observations as they emerge.</p>'

    technical_section = f"""
        <div class="section">
          <h2 class="section-header">
            Opportunities You Might Have Missed
            <span class="educational-badge">Learning Resource</span>
          </h2>
          {technical_cards}
        </div>
        """

    db_size_mb = get_database_size()
    db_size_note = f"Database size: {db_size_mb:.3f} MB"
    if db_size_mb > get_settings().DB_SIZE_WARNING_MB:
        db_size_note += " (WARNING: above monitoring threshold)"

    template = _load_email_template()
    week_of = datetime.date.today().strftime("%b %d, %Y")
    subtitle = f"Independent research and technical analysis for learning - Week of {week_of}"
    return (
        template.replace("{{TITLE}}", "Weekly Market Research Newsletter")
        .replace("{{SUBTITLE}}", subtitle)
        .replace("{{WATCHLIST_SECTION}}", watchlist_section)
        .replace(
            "{{TECHNICAL_SECTION}}",
            technical_section + f'<p class="disclaimer"><strong>System:</strong> {db_size_note}</p>',
        )
        .replace("{{LOGO_BLOCK}}", _get_logo_block())
    )


@lru_cache(maxsize=1)
def _load_email_template() -> str:
    template_path = os.path.join(os.path.dirname(__file__), "..", "templates", "email_report.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

@lru_cache(maxsize=1)
def _get_logo_path() -> str | None:
    logo_path = os.path.join(os.path.dirname(__file__), "..", "templates", "anveshq_logo.png")
    return logo_path if os.path.exists(logo_path) else None

@lru_cache(maxsize=1)
def _get_logo_block() -> str:
    if _get_logo_path():
        return '<img src="cid:anveshq_logo" alt="Anveshq" class="logo-image" />'
    return '<div class="header-title">Anveshq</div>'

# --- 3. EMAIL SENDER ---
def send_email(html_content: str) -> bool:
    """
    Sends the email report using SMTP settings from .env (configurable for Gmail or any provider).
    - Gmail: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_USE_SSL=false (STARTTLS).
    - Other providers: set SMTP_HOST, SMTP_PORT, and SMTP_USE_SSL=true for port 465.
    """
    settings = get_settings()
    sender_email = settings.SMTP_USER
    receiver_email = settings.TO_EMAIL
    password = settings.SMTP_PASSWORD
    smtp_host = settings.SMTP_HOST or ""
    smtp_port = settings.SMTP_PORT or 0
    use_ssl = getattr(settings, "SMTP_USE_SSL", False)

    if not all([sender_email, receiver_email, smtp_host, smtp_port, password]):
        logger.warning(
            "Email configuration incomplete (need SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, TO_EMAIL). Skipping send."
        )
        return False

    if smtp_host.strip().lower() in ("localhost", "127.0.0.1"):
        logger.warning(
            "SMTP_HOST is set to %s; no local SMTP server is running. "
            "To send real email, set in Backend/.env: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, "
            "SMTP_USE_SSL=false, SMTP_USER=your@gmail.com, SMTP_PASSWORD=<app password>, TO_EMAIL=recipient@example.com. "
            "See Backend/.env.example.",
            smtp_host,
        )
        return False

    logger.info("Sending report via %s:%s (SSL=%s)", smtp_host, smtp_port, use_ssl)

    message = MIMEMultipart("related")
    message["Subject"] = f"Anveshq Weekly Report - {datetime.date.today()}"
    message["From"] = sender_email
    message["To"] = receiver_email

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(html_content, "html"))
    message.attach(alternative)

    logo_path = _get_logo_path()
    if logo_path:
        try:
            with open(logo_path, "rb") as img:
                logo = MIMEImage(img.read())
            logo.add_header("Content-ID", "<anveshq_logo>")
            logo.add_header("Content-Disposition", "inline", filename="anveshq_logo.png")
            message.attach(logo)
        except Exception:
            logger.warning("Logo attachment failed; continuing without inline image.")

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
                server.login(sender_email, password)
                server.sendmail(sender_email, receiver_email, message.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(sender_email, password)
                server.sendmail(sender_email, receiver_email, message.as_string())
        logger.info("Email sent successfully to %s", receiver_email)
        return True
    except Exception as e:
        logger.exception("Failed to send email: %s", e)
        return False

# --- 4. MAIN ORCHESTRATOR ---
def run_report() -> None:
    """Generate weekly report from DB and send via configured SMTP (from .env). No graphs."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()],
    )
    logger.info("Generating weekly email report...")
    with get_db_context() as session:
        top_picks = get_top_picks(session)
        exclude = {s.symbol for s in top_picks}
        candidates = get_missed_opportunities(session, exclude_symbols=exclude, limit=100)
        settings = get_settings()
        missed_opportunities: list[MomentumStock] = []
        roi_map: dict[str, float | None] = {}
        max_missed = 4

        def try_add_opportunities(require_near_high: bool, require_positive_roi: bool, allow_missing_roi: bool) -> None:
            for stock in candidates:
                if stock in missed_opportunities:
                    continue
                if stock.rank_score is not None and stock.rank_score < 3:
                    continue
                if stock.daily_rank_delta is not None and stock.daily_rank_delta < 1:
                    continue
                if stock.risk_score is not None and stock.risk_score > 3:
                    continue
                if stock.is_fundamental_ok is False:
                    continue
                if stock.is_volume_confirmed is False:
                    continue

                snapshot = _get_market_snapshot(stock.symbol)
                current_price = snapshot.get("current_price") or stock.current_price
                high_52 = snapshot.get("high_52") or stock.high_52_week_price
                if require_near_high and current_price and high_52:
                    if current_price < (high_52 * settings.NEAR_52_WEEK_HIGH_THRESHOLD):
                        continue

                roi = calculate_roi(stock.symbol)
                if roi is None and not allow_missing_roi:
                    continue
                if require_positive_roi and roi < 0:
                    continue

                missed_opportunities.append(stock)
                roi_map[stock.symbol] = roi
                if len(missed_opportunities) >= max_missed:
                    return

        # Pass 1: strict (near 52-week high + positive ROI)
        try_add_opportunities(require_near_high=True, require_positive_roi=True, allow_missing_roi=False)
        # Pass 2: relax near-high requirement
        if len(missed_opportunities) < max_missed:
            try_add_opportunities(require_near_high=False, require_positive_roi=True, allow_missing_roi=False)
        # Pass 3: allow negative ROI if still empty
        if len(missed_opportunities) < max_missed:
            try_add_opportunities(require_near_high=False, require_positive_roi=False, allow_missing_roi=True)
        # Pass 4: ensure at least a few technical cards for the email
        if not missed_opportunities and candidates:
            for stock in candidates:
                if stock.symbol in exclude:
                    continue
                if stock in missed_opportunities:
                    continue
                missed_opportunities.append(stock)
                roi_map[stock.symbol] = calculate_roi(stock.symbol)
                if len(missed_opportunities) >= min(2, max_missed):
                    break
        html_content = generate_email_html(top_picks, missed_opportunities, roi_map)
        send_email(html_content)
    logger.info("Report generation complete.")


if __name__ == "__main__":
    run_report()
