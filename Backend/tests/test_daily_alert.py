import datetime as dt
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.config import get_settings
from src.daily_alert import (
    build_daily_alert_html,
    get_todays_new_signals,
    get_weekly_unique_signals,
    send_daily_alert,
)
from src.database import get_db_context, get_engine, reset_db_components
from src.models import Base, MomentumStock


@pytest.fixture
def configured_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_anveshq.db"
    monkeypatch.setenv("MODE", "TEST")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("TEST_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DB_PASSWORD", "")
    get_settings.cache_clear()
    reset_db_components()
    Base.metadata.create_all(bind=get_engine())
    yield
    reset_db_components()
    get_settings.cache_clear()


def _stock(symbol: str, seen_date: dt.date, risk_score: int = 1) -> MomentumStock:
    return MomentumStock(
        symbol=symbol,
        company_name=symbol,
        last_seen_date=seen_date,
        rank_score=4,
        daily_rank_delta=2,
        risk_score=risk_score,
        is_fundamental_ok=True,
        is_volume_confirmed=True,
        current_price=100.0,
        stop_loss_price=92.0,
        take_profit_price=115.0,
        position_shares=10,
        position_value=1_000.0,
        position_size_pct=1.0,
    )


def test_get_todays_new_signals_only_today(configured_environment):
    today = dt.date.today()
    with get_db_context() as session:
        session.add_all([_stock("TODAY.NS", today), _stock("OLD.NS", today - dt.timedelta(days=1))])

    with get_db_context() as session:
        signals = get_todays_new_signals(session, get_settings(), today)

    assert [signal["symbol"] for signal in signals] == ["TODAY.NS"]


def test_get_todays_new_signals_quality_filter(configured_environment):
    today = dt.date.today()
    with get_db_context() as session:
        session.add(_stock("RISKY.NS", today, risk_score=4))

    with get_db_context() as session:
        signals = get_todays_new_signals(session, get_settings(), today)

    assert signals == []


def test_get_weekly_unique_signals_deduplication():
    today = dt.date(2026, 5, 15)
    monday = today - dt.timedelta(days=today.weekday())
    rows = [
        SimpleNamespace(symbol="AAA.NS", company_name="AAA", current_price=100.0, rank_score=3, last_seen_date=monday),
        SimpleNamespace(symbol="AAA.NS", company_name="AAA", current_price=102.0, rank_score=5, last_seen_date=monday + dt.timedelta(days=2)),
        SimpleNamespace(symbol="BBB.NS", company_name="BBB", current_price=50.0, rank_score=4, last_seen_date=monday + dt.timedelta(days=1)),
    ]

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return rows

    class _Session:
        def execute(self, stmt):
            return _Result()

    signals = get_weekly_unique_signals(_Session(), today, limit=7)

    assert [signal["symbol"] for signal in signals] == ["AAA.NS", "BBB.NS"]
    assert signals[0]["rank_score"] == 5


def test_build_daily_alert_html_no_signals():
    html = build_daily_alert_html([], [], False, [], True, get_settings())

    assert "No qualifying signals" in html


def test_build_daily_alert_html_with_signals():
    signals = [
        {"symbol": "AAA.NS", "company_name": "Alpha", "current_price": 100.0, "stop_loss_price": 92.0, "take_profit_price": 115.0, "risk_score": 1, "rank_score": 4, "position_shares": 10, "position_value": 1_000.0},
        {"symbol": "BBB.NS", "company_name": "Beta", "current_price": 50.0, "stop_loss_price": 46.0, "take_profit_price": 57.5, "risk_score": 2, "rank_score": 5, "position_shares": 20, "position_value": 1_000.0},
    ]

    html = build_daily_alert_html(signals, [], False, [], True, get_settings())

    assert "AAA" in html
    assert "BBB" in html


def test_build_daily_alert_html_friday():
    weekly = [{"symbol": "AAA.NS", "current_price": 100.0, "rank_score": 5, "last_seen_date": dt.date(2026, 5, 13)}]

    html = build_daily_alert_html([], [], True, weekly, True, get_settings())

    assert "Week Summary" in html


def test_build_daily_alert_html_no_class_attribute():
    html = build_daily_alert_html([], [], False, [], True, get_settings())

    assert "class=" not in html


def test_send_daily_alert_skips_non_friday_no_signals(monkeypatch: pytest.MonkeyPatch):
    called = False

    class _SMTP:
        def __init__(self, *args, **kwargs):
            nonlocal called
            called = True

    monkeypatch.setattr("src.daily_alert.smtplib.SMTP", _SMTP)

    assert send_daily_alert("", signal_count=0, exit_count=0, is_friday=False) is False
    assert called is False
