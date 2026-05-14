import datetime
import html
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import and_, desc, select
from sqlalchemy.exc import SQLAlchemyError

from src.config import get_settings
from src.database import get_db_context
from src.models import MomentumStock
from src.services import MarketRegimeChecker

logger = logging.getLogger("Anveshq.DailyAlert")

__all__ = ["run_daily_alert"]


def _symbol_short(symbol: str | None) -> str:
    return (symbol or "").replace(".NS", "").replace(".BO", "")


def _format_price(value) -> str:
    if isinstance(value, (int, float)):
        return f"Rs. {value:,.2f}"
    return "--"


def _format_pct(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return "--"


def _format_date(value) -> str:
    return value.strftime("%d %b") if hasattr(value, "strftime") else "--"


def get_todays_new_signals(session, settings_obj, today: datetime.date, limit: int = 5) -> list[dict]:
    stmt = (
        select(MomentumStock)
        .where(
            MomentumStock.last_seen_date == today,
            MomentumStock.rank_score >= 3,
            MomentumStock.daily_rank_delta >= 1,
            MomentumStock.risk_score <= 3,
            MomentumStock.is_fundamental_ok.is_(True),
            MomentumStock.is_volume_confirmed.is_(True),
        )
        .order_by(desc(MomentumStock.daily_rank_delta), desc(MomentumStock.rank_score))
        .limit(limit)
    )
    try:
        rows = session.execute(stmt).scalars().all()
    except SQLAlchemyError as exc:
        logger.warning("Daily alert signal query failed: %s", exc)
        return []
    return [
        {
            "symbol": row.symbol,
            "company_name": row.company_name,
            "current_price": row.current_price,
            "stop_loss_price": row.stop_loss_price,
            "take_profit_price": row.take_profit_price,
            "risk_score": row.risk_score,
            "rank_score": row.rank_score,
            "position_shares": row.position_shares,
            "position_value": row.position_value,
            "position_size_pct": row.position_size_pct,
        }
        for row in rows
    ]


def get_exit_alerts(session, today: datetime.date) -> list[dict]:
    try:
        rows = session.execute(
            select(MomentumStock).where(MomentumStock.exit_date == today)
        ).scalars().all()
    except SQLAlchemyError as exc:
        logger.warning("Daily alert exit query failed: %s", exc)
        return []
    alerts: list[dict] = []
    for row in rows:
        holding_days = None
        if row.exit_date and row.entry_date:
            holding_days = (row.exit_date - row.entry_date).days
        alerts.append(
            {
                "symbol": row.symbol,
                "company_name": row.company_name,
                "entry_price": row.entry_price,
                "exit_price": row.exit_price,
                "realized_return_pct": row.realized_return_pct,
                "exit_reason": row.exit_reason,
                "holding_days": holding_days,
            }
        )
    return alerts


def get_weekly_unique_signals(session, today: datetime.date, limit: int = 7) -> list[dict]:
    week_start = today - datetime.timedelta(days=today.weekday())
    try:
        rows = session.execute(
            select(MomentumStock)
            .where(
                and_(
                    MomentumStock.last_seen_date >= week_start,
                    MomentumStock.last_seen_date <= today,
                    MomentumStock.last_seen_date != today,
                    MomentumStock.rank_score >= 3,
                    MomentumStock.daily_rank_delta >= 1,
                )
            )
            .order_by(desc(MomentumStock.rank_score))
        ).scalars().all()
    except SQLAlchemyError as exc:
        logger.warning("Daily alert weekly summary query failed: %s", exc)
        return []

    best_by_symbol: dict[str, MomentumStock] = {}
    for row in rows:
        current = best_by_symbol.get(row.symbol)
        if current is None or row.rank_score > current.rank_score:
            best_by_symbol[row.symbol] = row

    return [
        {
            "symbol": row.symbol,
            "company_name": row.company_name,
            "current_price": row.current_price,
            "rank_score": row.rank_score,
            "last_seen_date": row.last_seen_date,
        }
        for row in sorted(best_by_symbol.values(), key=lambda item: item.rank_score, reverse=True)[:limit]
    ]


def build_daily_alert_html(
    new_signals: list,
    exit_alerts: list,
    is_friday: bool,
    weekly_unique: list,
    is_bull: bool,
    settings_obj,
) -> str:
    today = datetime.date.today()
    regime_color = "#059669" if is_bull else "#dc2626"
    regime_label = "BULL ↑" if is_bull else "BEAR/SIDEWAYS ↓"
    parts = [
        "<div style='max-width:480px;margin:0 auto;padding:16px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#fff;color:#0f172a'>",
        "<div style='border-bottom:2px solid #0f172a;padding-bottom:12px;margin-bottom:16px'>"
        "<h2 style='margin:0;font-size:18px;font-weight:700'>Anveshq Daily Alert</h2>"
        f"<p style='margin:4px 0 0;font-size:12px;color:#64748b'>{today.strftime('%A')}, {today.strftime('%d %b %Y')} &nbsp;|&nbsp; {len(new_signals)} new signal(s) &nbsp;|&nbsp; Market: <strong style='color:{regime_color}'>{regime_label}</strong></p>"
        "</div>",
    ]

    if new_signals:
        parts.append(
            "<h3 style='font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#1e293b;margin:0 0 10px'>New Signals — Entry Tomorrow Open</h3>"
        )
        for signal in new_signals:
            name = html.escape(signal.get("company_name") or signal.get("symbol") or "")
            symbol = html.escape(_symbol_short(signal.get("symbol")))
            parts.append(
                "<div style='border:1px solid #e2e8f0;border-left:3px solid #3b82f6;border-radius:6px;padding:10px 12px;margin-bottom:8px'>"
                f"<div style='font-size:14px;font-weight:700'>{name} <span style='font-size:12px;color:#64748b;font-weight:400'>({symbol})</span></div>"
                f"<div style='font-size:12px;color:#475569;margin-top:4px'>CMP: <strong>{_format_price(signal.get('current_price'))}</strong> &nbsp;|&nbsp; Stop: <strong style='color:#dc2626'>{_format_price(signal.get('stop_loss_price'))}</strong> &nbsp;|&nbsp; Target: <strong style='color:#059669'>{_format_price(signal.get('take_profit_price'))}</strong></div>"
                f"<div style='font-size:11px;color:#94a3b8;margin-top:3px'>Risk Score: {signal.get('risk_score')}/7 &nbsp;|&nbsp; Rank: {signal.get('rank_score')} &nbsp;|&nbsp; Suggested: {signal.get('position_shares') or '--'} shares (~{_format_price(signal.get('position_value'))})</div>"
                "</div>"
            )
        parts.append(
            "<p style='font-size:11px;color:#94a3b8;margin:4px 0 16px'>Place order at next open. Always verify independently.</p>"
        )

    if exit_alerts:
        parts.append(
            "<h3 style='font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#1e293b;margin:0 0 10px'>Exit Alerts</h3>"
        )
        for alert in exit_alerts:
            return_pct = alert.get("realized_return_pct")
            color = "#059669" if isinstance(return_pct, (int, float)) and return_pct >= 0 else "#dc2626"
            name = html.escape(alert.get("company_name") or alert.get("symbol") or "")
            reason = html.escape(alert.get("exit_reason") or "--")
            parts.append(
                f"<div style='border:1px solid #e2e8f0;border-left:3px solid {color};border-radius:6px;padding:10px 12px;margin-bottom:8px'>"
                f"<div style='font-size:14px;font-weight:700'>{name} &nbsp;<span style='font-size:13px;color:{color}'>{_format_pct(return_pct)}%</span></div>"
                f"<div style='font-size:11px;color:#64748b;margin-top:3px'>Entry {_format_price(alert.get('entry_price'))} → Exit {_format_price(alert.get('exit_price'))} &nbsp;|&nbsp; {alert.get('holding_days') or '--'} days &nbsp;|&nbsp; Reason: {reason}</div>"
                "</div>"
            )

    if not new_signals and not exit_alerts:
        parts.append(
            "<div style='background:#f8fafc;border-radius:6px;padding:14px;text-align:center'><p style='font-size:13px;color:#64748b;margin:0'>No qualifying signals today.<br><span style='font-size:11px'>Market conditions did not generate breakouts meeting all filters. Weekly report arrives Sunday.</span></p></div>"
        )

    if is_friday and weekly_unique:
        rows = []
        for signal in weekly_unique:
            rows.append(
                "<tr style='border-bottom:1px solid #f1f5f9'>"
                f"<td style='padding:5px 0;font-weight:600'>{html.escape(_symbol_short(signal.get('symbol')))}</td>"
                f"<td style='text-align:right;padding:5px 0'>{_format_price(signal.get('current_price'))}</td>"
                f"<td style='text-align:right;padding:5px 0'>{signal.get('rank_score')}</td>"
                f"<td style='text-align:right;padding:5px 0;color:#64748b'>{_format_date(signal.get('last_seen_date'))}</td>"
                "</tr>"
            )
        parts.append(
            "<h3 style='font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#7c3aed;margin:16px 0 10px'>Week Summary — All Unique Signals</h3>"
            "<table style='width:100%;border-collapse:collapse;font-size:12px'>"
            "<tr style='border-bottom:1px solid #e2e8f0'><th style='text-align:left;padding:4px 0;color:#64748b;font-weight:600'>Symbol</th><th style='text-align:right;padding:4px 0;color:#64748b;font-weight:600'>CMP</th><th style='text-align:right;padding:4px 0;color:#64748b;font-weight:600'>Rank</th><th style='text-align:right;padding:4px 0;color:#64748b;font-weight:600'>Last Signal</th></tr>"
            f"{''.join(rows)}</table>"
        )

    parts.append(
        "<div style='margin-top:20px;padding-top:12px;border-top:1px solid #e2e8f0;font-size:10px;color:#94a3b8;line-height:1.5'>Educational purposes only. Not investment advice. Not SEBI registered. Verify all signals independently before trading.</div>"
    )
    parts.append("</div>")
    return "".join(parts)


def send_daily_alert(html_content: str, signal_count: int, exit_count: int, is_friday: bool) -> bool:
    settings = get_settings()
    if signal_count == 0 and exit_count == 0 and not is_friday:
        logger.info("No signals and not Friday — skipping send")
        return False

    sender_email = settings.SMTP_USER
    receiver_email = settings.TO_EMAIL
    password = settings.SMTP_PASSWORD
    smtp_host = settings.SMTP_HOST or ""
    smtp_port = settings.SMTP_PORT or 0
    use_ssl = getattr(settings, "SMTP_USE_SSL", False)
    missing_email_settings = [
        name
        for name, value in {
            "SMTP_HOST": smtp_host,
            "SMTP_PORT": smtp_port,
            "SMTP_USER": sender_email,
            "SMTP_PASSWORD": password,
            "TO_EMAIL": receiver_email,
        }.items()
        if not value
    ]
    if missing_email_settings:
        logger.warning(
            "Daily alert email configuration incomplete; missing or blank: %s. Skipping send.",
            ", ".join(missing_email_settings),
        )
        return False

    subject = f"Anveshq Alert — {signal_count} Signal(s) | {datetime.date.today().strftime('%d %b %Y')}"
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
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
        return True
    except Exception as exc:
        logger.warning("Daily alert SMTP send failed: %s", exc)
        return False


def run_daily_alert() -> None:
    logging.basicConfig(level=logging.INFO, format="[ANVESHQ:DAILY] [%(levelname)s] %(message)s")
    settings = get_settings()
    if not settings.DAILY_ALERT_ENABLED:
        logger.info("DAILY_ALERT_ENABLED=False, skipping")
        return

    today = datetime.date.today()
    if today.weekday() >= 5:
        logger.info("Weekend — skipping daily alert")
        return

    is_friday = today.weekday() == 4
    is_bull = MarketRegimeChecker.is_bull_market(settings) if settings.MARKET_REGIME_FILTER_ENABLED else True
    with get_db_context() as session:
        new_signals = get_todays_new_signals(session, settings, today, limit=5)
        exit_alerts = get_exit_alerts(session, today)
        weekly_unique = get_weekly_unique_signals(session, today, limit=7) if is_friday else []

    html_content = build_daily_alert_html(new_signals, exit_alerts, is_friday, weekly_unique, is_bull, settings)
    sent = send_daily_alert(html_content, len(new_signals), len(exit_alerts), is_friday)
    logger.info("Daily alert: signals=%s exits=%s sent=%s", len(new_signals), len(exit_alerts), sent)


if __name__ == "__main__":
    run_daily_alert()
