import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.config import get_settings
from src.database import get_db_context, get_engine, reset_db_components
from src.earnings_calendar import EarningsCalendar
from src.backtest import compute_net_return
from src.exit_manager import ExitManager
from src.models import Base, MomentumStock
from src.paper_trader import PaperTrader
from src.position_sizing import PositionSizer
from src.quality_screener import QualityScreener
from src.services import RiskAndQualityAnalyzer


@pytest.fixture
def configured_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_anveshq.db"
    monkeypatch.setenv("MODE", "TEST")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("TEST_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DB_PASSWORD", "")
    monkeypatch.setenv("MARKET_REGIME_FILTER_ENABLED", "false")
    get_settings.cache_clear()
    reset_db_components()
    Base.metadata.create_all(bind=get_engine())
    yield
    reset_db_components()
    get_settings.cache_clear()


def test_position_sizer_calculates_fixed_fractional_position(configured_environment):
    settings = get_settings()

    position = PositionSizer.calculate_position(1_000_000, 100.0, 92.0, settings)

    assert position["shares"] == 1500
    assert position["position_value"] == 150_000
    assert position["position_pct"] == 15.0
    assert position["risk_pct_actual"] == 1.2


def test_position_sizer_rejects_invalid_stop(configured_environment):
    settings = get_settings()

    assert PositionSizer.calculate_position(1_000_000, 100.0, 101.0, settings) is None


def test_exit_manager_updates_trailing_stop_and_exits(configured_environment):
    settings = get_settings()
    today = dt.date.today()
    with get_db_context() as session:
        session.add(
            MomentumStock(
                symbol="TRAIL.NS",
                last_seen_date=today,
                rank_score=5,
                daily_rank_delta=1,
                current_price=100.0,
                entry_date=today - dt.timedelta(days=10),
                entry_price=100.0,
                high_water_mark=120.0,
                trailing_stop_price=111.6,
                is_active=True,
            )
        )

    with get_db_context() as session:
        exited = ExitManager.update_trailing_stops(session, settings, today)

    assert exited[0]["exit_reason"] == "TRAILING_STOP"
    with get_db_context() as session:
        stock = session.execute(select(MomentumStock).where(MomentumStock.symbol == "TRAIL.NS")).scalar_one()
        assert stock.exit_reason == "TRAILING_STOP"
        assert stock.realized_return_pct == 0.0


def test_earnings_calendar_detects_near_earnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache_file = tmp_path / "earnings_cache.json"
    monkeypatch.setattr("src.earnings_calendar.CACHE_FILE", cache_file)
    today = dt.date(2026, 5, 9)
    cache_file.write_text(
        '{"ABC.NS": {"earnings_date": "2026-05-12", "fetched_date": "2026-05-09"}}',
        encoding="utf-8",
    )

    is_near, reason = EarningsCalendar.is_near_earnings("ABC.NS", today, get_settings())

    assert is_near
    assert "Earnings in 3 days" in reason


def test_relative_strength_requires_outperformance(configured_environment):
    settings = get_settings()
    stock_df = pd.DataFrame({"Close": [100.0] * 20 + [110.0]})
    nifty_df = pd.DataFrame({"Close": [100.0] * 20 + [108.0]})

    is_ok, reason = RiskAndQualityAnalyzer.relative_strength_check(stock_df, nifty_df, settings)

    assert not is_ok
    assert "Weak relative strength" in reason


def test_relative_strength_check_pass(configured_environment, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_MIN_OUTPERFORMANCE_PCT", "3.0")
    get_settings.cache_clear()
    settings = get_settings()
    stock_df = pd.DataFrame({"Close": [100.0] * 20 + [108.0]})
    nifty_df = pd.DataFrame({"Close": [100.0] * 20 + [103.0]})

    assert RiskAndQualityAnalyzer.relative_strength_check(stock_df, nifty_df, settings) == (True, None)


def test_relative_strength_check_fail(configured_environment, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_MIN_OUTPERFORMANCE_PCT", "3.0")
    get_settings.cache_clear()
    settings = get_settings()
    stock_df = pd.DataFrame({"Close": [100.0] * 20 + [102.0]})
    nifty_df = pd.DataFrame({"Close": [100.0] * 20 + [104.0]})

    is_ok, reason = RiskAndQualityAnalyzer.relative_strength_check(stock_df, nifty_df, settings)

    assert is_ok is False
    assert isinstance(reason, str)


def test_relative_strength_check_disabled(configured_environment, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_FILTER_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    stock_df = pd.DataFrame({"Close": [100.0] * 20 + [90.0]})
    nifty_df = pd.DataFrame({"Close": [100.0] * 20 + [120.0]})

    assert RiskAndQualityAnalyzer.relative_strength_check(stock_df, nifty_df, settings) == (True, None)


def test_relative_strength_check_insufficient_data(configured_environment):
    settings = get_settings()
    stock_df = pd.DataFrame({"Close": [100.0, 101.0]})
    nifty_df = pd.DataFrame({"Close": [100.0, 101.0]})

    assert RiskAndQualityAnalyzer.relative_strength_check(stock_df, nifty_df, settings) == (True, None)


def test_compute_net_return_reduces_gross(configured_environment):
    net_return = compute_net_return(10.0, 100.0, 110.0, 10, 15, get_settings())

    assert net_return is not None
    assert net_return < 10.0
    assert net_return > 7.0


def test_paper_trader_opens_and_updates_trade(configured_environment):
    settings = get_settings()
    today = dt.date.today()
    with get_db_context() as session:
        stock = MomentumStock(
            symbol="PAPER.NS",
            last_seen_date=today,
            rank_score=5,
            risk_score=1,
            current_price=100.0,
            stop_loss_price=92.0,
            take_profit_price=115.0,
            position_shares=100,
            position_value=10_000.0,
            entry_date=today - dt.timedelta(days=10),
            entry_price=100.0,
            exit_date=today,
            exit_price=110.0,
            exit_reason="TIME_EXIT",
        )
        session.add(stock)
        PaperTrader.open_trade(session, stock, settings)

    with get_db_context() as session:
        closed = PaperTrader.update_open_trades(session, settings, today)
        summary = PaperTrader.get_performance_summary(session)

    assert len(closed) == 1
    assert summary["closed_positions"] == 1
    assert summary["win_rate_pct"] == 100.0


def test_quality_screener_filters_and_scores(configured_environment, monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(
        "src.quality_screener.RiskAndQualityAnalyzer.get_fundamentals_with_fallback",
        lambda symbol: {
            "trailingPE": 18.0,
            "debtToEquity": 0.2,
            "returnOnEquity": 0.2,
            "promoterHoldingPercent": 55.0,
        },
    )
    history = pd.DataFrame(
        {"Close": [80.0], "High": [100.0], "Volume": [10_000]},
        index=[pd.Timestamp("2026-05-09")],
    )
    monkeypatch.setattr("src.quality_screener.download_history", lambda *args, **kwargs: history)

    results = QualityScreener.screen_quality_stocks(["ABC.NS"], settings)

    assert results[0]["symbol"] == "ABC.NS"
    assert results[0]["price_vs_52w_high_pct"] == 80.0
