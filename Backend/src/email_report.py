import logging
import smtplib
import ssl
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import yfinance as yf
import pandas as pd
from sqlalchemy.orm import Session
from src.database import get_db_context
from src.models import MomentumStock
from src.config import get_settings
from src.yahoo_finance import get_ticker
from src.services import RiskAndQualityAnalyzer
from sqlalchemy import select, desc, asc
import datetime

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


def _get_nse_quote(symbol: str) -> dict | None:
    if not symbol.endswith(".NS"):
        return None
    if symbol in _nse_quote_cache:
        return _nse_quote_cache[symbol]
    try:
        from nsetools import Nse
    except Exception:
        return None

    try:
        nse = Nse()
        quote = nse.get_quote(symbol.replace(".NS", ""))
        if isinstance(quote, dict):
            _nse_quote_cache[symbol] = quote
            return quote
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
        info = ticker.info or {}
    except Exception:
        info = {}

    market_cap = info.get("marketCap")
    pe_ratio = info.get("trailingPE") or info.get("forwardPE")
    debt_to_equity = info.get("debtToEquity")
    shares_outstanding = info.get("sharesOutstanding") or info.get("shares")
    trailing_eps = info.get("trailingEps") or info.get("epsTrailingTwelveMonths")

    fast_info = None
    if ticker is not None:
        try:
            fast_info = ticker.fast_info
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

    if market_cap is None or pe_ratio is None:
        try:
            fallback = RiskAndQualityAnalyzer.get_fundamentals_from_google_finance(symbol)
            if fallback:
                market_cap = market_cap or fallback.get("marketCap")
                pe_ratio = pe_ratio or fallback.get("trailingPE")
        except Exception:
            pass

    if (market_cap is None or pe_ratio is None or debt_to_equity is None) and symbol.endswith(".NS"):
        quote = _get_nse_quote(symbol)
        if quote:
            if market_cap is None:
                market_cap = _parse_number(
                    quote.get("marketCapFull") or quote.get("marketCap") or quote.get("marketCapValue")
                )
            if pe_ratio is None:
                pe_ratio = _parse_number(quote.get("pE") or quote.get("pe") or quote.get("priceEarnings"))
            if debt_to_equity is None:
                debt_to_equity = _parse_number(quote.get("debtEquity") or quote.get("debtToEquity"))

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
        df = yf.download(symbol, period="1y", interval="1d", progress=False, auto_adjust=False)
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


def _rsi_comment(rsi: float | None) -> str:
    if rsi is None:
        return "RSI data is unavailable."
    if rsi >= 60:
        return f"RSI is at {rsi:.1f}, indicating positive momentum."
    if rsi >= 45:
        return f"RSI is at {rsi:.1f}, indicating neutral momentum."
    return f"RSI is at {rsi:.1f}, indicating weak momentum."


def _build_stock_card_html(stock: MomentumStock, roi_value: float | None = None) -> str:
    snapshot = _get_market_snapshot(stock.symbol)
    current_price = snapshot.get("current_price") or getattr(stock, "current_price", None)
    fundamentals = _get_fundamentals(stock.symbol, current_price=current_price)

    name = _display_name(stock)
    exchange = _exchange_label(stock.symbol)
    url = _google_search_url(stock.symbol)

    current_price = snapshot.get("current_price") or getattr(stock, "current_price", None)
    day_change = snapshot.get("day_change_pct")

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

    volume = snapshot.get("volume")
    avg_volume = snapshot.get("avg_volume_20")
    volume_delta = snapshot.get("volume_vs_avg_pct")
    if volume is not None and avg_volume is not None and avg_volume > 0 and volume_delta is not None:
        if volume_delta >= 20:
            volume_text = f"Volume is {_format_signed_percent(volume_delta)} above the 20 day average."
        elif volume_delta <= -20:
            volume_text = f"Volume is {_format_signed_percent(volume_delta)} below the 20 day average."
        else:
            volume_text = "Volume is near the 20 day average."
    else:
        volume_text = "Volume data is unavailable."

    support = snapshot.get("support")
    resistance = snapshot.get("resistance")
    support_text = f"Immediate support zone observed near {_format_price(support)}." if support else "Support data is unavailable."
    resistance_text = f"Near-term resistance zone observed around {_format_price(resistance)}." if resistance else "Resistance data is unavailable."

    rsi_text = _rsi_comment(snapshot.get("rsi"))

    pe_ratio = fundamentals.get("trailingPE")
    market_cap = fundamentals.get("marketCap")
    debt_to_equity = fundamentals.get("debtToEquity")
    market_cap_str = _format_inr(float(market_cap)) if isinstance(market_cap, (int, float)) else "--"

    high_52 = snapshot.get("high_52") or getattr(stock, "high_52_week_price", None)
    low_52 = snapshot.get("low_52") or getattr(stock, "low_52_week", None)
    high_52_date = snapshot.get("high_52_date") or getattr(stock, "high_52_week_date", None)
    low_52_date = snapshot.get("low_52_date") or getattr(stock, "low_52_week_date", None)

    market_view = "The stock is currently showing strength on the daily timeframe."
    if not (price_above_20 and price_above_50) or (snapshot.get("rsi") is not None and snapshot.get("rsi") < 50):
        market_view = "The stock is showing mixed signals on the daily timeframe."

    roi_line = ""
    if roi_value is not None:
        total_amount = 100000 * (1 + float(roi_value) / 100)
        roi_line = f"<div><strong>Weekly ROI:</strong> {float(roi_value):.2f}%. 1L Rs. would become <strong>{_format_inr(total_amount)}</strong></div>"

    return f"""
        <div class="stock-card">
            <div class="stock-info">
                <div class="stock-name"><a href="{url}" target="_blank" rel="noopener">Stock: {name} ({exchange})</a></div>
                <div class="stock-insight">Market Snapshot:</div>
                <ul>
                    <li><strong>Current Price:</strong> {_format_price(current_price)}</li>
                    <li><strong>Day Change:</strong> {_format_signed_percent(day_change)}</li>
                    <li><strong>P/E Ratio:</strong> {_format_numeric(pe_ratio)}</li>
                    <li><strong>Market Cap:</strong> {market_cap_str}</li>
                    <li><strong>Debt/Equity:</strong> {_format_numeric(debt_to_equity)}</li>
                    <li><strong>52-Week High:</strong> {_format_price(high_52)} on {_format_date(high_52_date)}</li>
                    <li><strong>52-Week Low:</strong> {_format_price(low_52)} on {_format_date(low_52_date)}</li>
                </ul>
                <div class="stock-insight">Technical Observations:</div>
                <ul>
                    <li>{ma_text}</li>
                    <li>{ema_text}</li>
                    <li>{rsi_text}</li>
                    <li>{volume_text}</li>
                    <li>{support_text}</li>
                    <li>{resistance_text}</li>
                </ul>
                <div class="stock-insight">Market View:</div>
                <div>{market_view} Traders and investors may review this setup as part of their own independent analysis and risk assessment.</div>
                {roi_line}
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
        df = yf.download(symbol, start=last_monday, end=last_friday + datetime.timedelta(days=1), progress=False)
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

    html = """
    <html>
    <head>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; }
            .container { max-width: 800px; margin: auto; padding: 20px; background-color: #f9f9f9; }
            .header { background-color: #4CAF50; color: white; padding: 10px; text-align: center; }
            .section { margin-top: 20px; }
            .section-title { font-size: 20px; color: #4CAF50; border-bottom: 2px solid #4CAF50; padding-bottom: 5px; }
            .stock-card { border: 1px solid #ddd; padding: 15px; margin-top: 15px; }
            .stock-info { }
            .stock-name { font-size: 24px; font-weight: bold; }
            .stock-name a { color: #1565c0; text-decoration: none; }
            .stock-name a:hover { text-decoration: underline; }
            .stock-price { color: #333; margin-top: 4px; }
            .stock-insight { font-style: italic; color: #555; margin-top: 8px; }
            .disclaimer { font-size: 12px; color: #777; margin-top: 30px; text-align: center; }
            @media (prefers-color-scheme: dark) {
                body { background-color: #121212; color: #eee; }
                .container { background-color: #1e1e1e; }
                .stock-card { border-color: #444; }
                .stock-insight { color: #aaa; }
                .stock-name a { color: #42a5f5; }
                .header { background-color: #5cb85c; }
                .section-title { color: #5cb85c; border-bottom-color: #5cb85c; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Anveshq Weekly Insights</h1>
            </div>
            <div class="section">
                <h2 class="section-title">Top Picks for Next Week</h2>
    """

    for stock in top_picks:
        html += _build_stock_card_html(stock)

    html += "</div>"

    if missed_opportunities:
        html += """
            <div class="section">
                <h2 class="section-title">Opportunities You Might Have Missed</h2>
        """
        for stock in missed_opportunities:
            roi_val = roi_map.get(stock.symbol)
            html += _build_stock_card_html(stock, roi_value=roi_val)
        html += "</div>"

    # --- FOOTER & DISCLAIMER ---
    html += """
            <div class="disclaimer">
                <p><strong>Disclaimer:</strong> This content is for informational purposes only and does not constitute investment advice.</p>
                <p>This analysis is auto-generated using publicly available market data. No personalized investment recommendation is provided.</p>
            </div>
        </div>
    </body>
    </html>
    """

    return html

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
    message.attach(MIMEText(html_content, "html"))

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
        missed_opportunities = get_missed_opportunities(session, exclude_symbols=exclude, limit=5)
        roi_map = {s.symbol: calculate_roi(s.symbol) for s in missed_opportunities}
        html_content = generate_email_html(top_picks, missed_opportunities, roi_map)
        send_email(html_content)
    logger.info("Report generation complete.")


if __name__ == "__main__":
    run_report()
