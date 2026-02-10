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
    """Format amount in Indian style (e.g. 1,08,390.73) with Rs. prefix."""
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


_fundamental_cache: dict[str, dict] = {}


def _get_fundamentals(symbol: str) -> dict:
    if symbol in _fundamental_cache:
        return _fundamental_cache[symbol]
    try:
        ticker = get_ticker(symbol)
        info = ticker.info or {}
        data = {
            "marketCap": info.get("marketCap"),
            "trailingPE": info.get("trailingPE"),
            "debtToEquity": info.get("debtToEquity"),
        }
    except Exception:
        data = {"marketCap": None, "trailingPE": None, "debtToEquity": None}
    _fundamental_cache[symbol] = data
    return data


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


def _build_metrics_html(stock: MomentumStock) -> str:
    fundamentals = _get_fundamentals(stock.symbol)
    current_price = getattr(stock, "current_price", None)
    high_52 = getattr(stock, "high_52_week_price", None)
    low_52 = getattr(stock, "low_52_week", None)

    high_distance = None
    low_distance = None
    if current_price and high_52:
        high_distance = ((current_price / high_52) - 1) * 100
    if current_price and low_52:
        low_distance = ((current_price / low_52) - 1) * 100

    pe_ratio = fundamentals.get("trailingPE")
    market_cap = fundamentals.get("marketCap")
    debt_to_equity = fundamentals.get("debtToEquity")

    market_cap_str = _format_inr(float(market_cap)) if isinstance(market_cap, (int, float)) else "--"
    volume_status = "Yes" if getattr(stock, "is_volume_confirmed", False) else "No"

    return f"""
        <ul>
            <li><strong>P/E Ratio:</strong> {_format_numeric(pe_ratio)}</li>
            <li><strong>Market Cap:</strong> {market_cap_str}</li>
            <li><strong>Debt/Equity:</strong> {_format_numeric(debt_to_equity)}</li>
            <li><strong>Distance From 52-Week High:</strong> {_format_percent(high_distance)}</li>
            <li><strong>Distance From 52-Week Low:</strong> {_format_percent(low_distance)}</li>
            <li><strong>Risk Score:</strong> {_format_numeric(getattr(stock, "risk_score", None))}</li>
            <li><strong>Volume Confirmed:</strong> {volume_status}</li>
        </ul>
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
        name = _display_name(stock)
        url = _google_search_url(stock.symbol)
        price_str = _format_inr(stock.current_price) if stock.current_price is not None else "--"
        html += f"""
        <div class="stock-card">
            <div class="stock-info">
                <div class="stock-name"><a href="{url}" target="_blank" rel="noopener">{name}</a></div>
                <div class="stock-price">Current price: {price_str}</div>
                <div class="stock-insight">Key fundamentals and technicals:</div>
                {_build_metrics_html(stock)}
            </div>
        </div>
        """

    html += "</div>"

    if missed_opportunities:
        html += """
            <div class="section">
                <h2 class="section-title">Opportunities You Might Have Missed</h2>
        """
        for stock in missed_opportunities:
            name = _display_name(stock)
            url = _google_search_url(stock.symbol)
            price_str = _format_inr(stock.current_price) if stock.current_price is not None else "--"
            roi_val = roi_map.get(stock.symbol)
            roi_line = ""
            if roi_val is not None:
                total_amount = 100000 * (1 + float(roi_val) / 100)
                roi_line = f"<div><strong>Weekly ROI:</strong> {float(roi_val):.2f}%. 1L Rs. would become <strong>{_format_inr(total_amount)}</strong></div>"
            html += f"""
                <div class="stock-card">
                    <div class="stock-info">
                        <div class="stock-name"><a href="{url}" target="_blank" rel="noopener">{name}</a></div>
                        <div class="stock-price">Current price: {price_str}</div>
                        <div class="stock-insight">Key fundamentals and technicals:</div>
                        {_build_metrics_html(stock)}
                        {roi_line}
                    </div>
                </div>
            """
        html += "</div>"

    # --- FOOTER & DISCLAIMER ---
    html += """
            <div class="disclaimer">
                <p><strong>Disclaimer:</strong> This is not financial advice. All information provided is for educational purposes only. Please consult with a qualified financial advisor before making any investment decisions. Stock market investments are subject to market risks.</p>
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
