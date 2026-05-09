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
from src.database import ensure_momentum_schema_columns, get_db_context, get_engine, reset_db_components
from src.models import Base, MomentumStock
from src.services import MarketRegimeChecker, MarketValidator, RankingEngine, RiskAndQualityAnalyzer, StockFetcher
from src.utils import Bhavcopy
from src.yahoo_finance import download_history, get_info, is_recoverable_yahoo_error


@pytest.fixture
def configured_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_anveshq.db"
    master_dir = tmp_path / "master"
    master_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("MODE", "TEST")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("TEST_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DB_PASSWORD", "")
    monkeypatch.setenv("MASTER_DATA_DIRECTORY", str(master_dir))
    monkeypatch.setenv("JSON_UNIVERSE_PATH", str(master_dir / "master-latest.json"))
    monkeypatch.setenv("MIN_HISTORY_DAYS", "150")
    monkeypatch.setenv("MARKET_REGIME_FILTER_ENABLED", "false")

    get_settings.cache_clear()
    reset_db_components()
    Base.metadata.create_all(bind=get_engine())
    yield
    reset_db_components()
    get_settings.cache_clear()


def test_validate_market_data_freshness_uses_expected_market_date(configured_environment):
    settings = get_settings()
    df = pd.DataFrame(
        {"Close": [100.0], "Volume": [1_000]},
        index=[pd.Timestamp("2026-03-27 18:30:00+00:00")],
    )

    assert MarketValidator.validate_market_data_freshness(
        df,
        settings,
        symbol="ABC.NS",
        expected_market_date=dt.date(2026, 3, 28),
    )
    assert not MarketValidator.validate_market_data_freshness(
        df,
        settings,
        symbol="ABC.NS",
        expected_market_date=dt.date(2026, 3, 31),
    )


def test_merge_market_data_prefers_bhavcopy_row_on_same_day(configured_environment):
    settings = get_settings()
    df_yf = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Volume": [1_000],
        },
        index=[pd.Timestamp("2026-03-28")],
    )
    bhavcopy_df = pd.DataFrame(
        [
            {
                "TckrSymb": "ABC",
                "BizDt": "2026-03-28",
                "OpnPric": 105.0,
                "HghPric": 110.0,
                "LwPric": 104.0,
                "ClsPric": 109.0,
                "TtlTradgVol": 2_000,
            }
        ]
    )

    merged_df, merge_info = StockFetcher._merge_market_data("ABC.NS", df_yf, bhavcopy_df, settings)

    assert len(merged_df) == 1
    assert float(merged_df["Close"].iloc[-1]) == 109.0
    assert merge_info["source"] == "bhavcopy_replaced_same_day_row"


def test_bhavcopy_url_generation_accepts_legacy_placeholder(configured_environment, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "BHAVCOPY_URL_TEMPLATE",
        "https://example.com/BhavCopy_{YYYYMMDD}.csv.zip",
    )
    get_settings.cache_clear()

    assert Bhavcopy.get_bhavcopy_url_for_date(dt.date(2026, 4, 6)) == (
        "https://example.com/BhavCopy_20260406.csv.zip"
    )


def test_bhavcopy_url_generation_keeps_backward_compatibility_for_date_placeholder(
    configured_environment, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        "BHAVCOPY_URL_TEMPLATE",
        "https://example.com/BhavCopy_{date}.csv.zip",
    )
    get_settings.cache_clear()

    assert Bhavcopy.get_bhavcopy_url_for_date(dt.date(2026, 4, 6)) == (
        "https://example.com/BhavCopy_20260406.csv.zip"
    )


def test_yahoo_download_history_returns_empty_dataframe_on_401(monkeypatch: pytest.MonkeyPatch):
    def raise_unauthorized(*args, **kwargs):
        raise Exception(
            'HTTP Error 401: {"finance":{"result":null,"error":{"code":"Unauthorized","description":"User is unable to access this feature"}}}'
        )

    monkeypatch.setattr("src.yahoo_finance.yf.download", raise_unauthorized)

    result = download_history("ABC.NS", period="1y")

    assert result.empty


def test_yahoo_get_info_returns_empty_dict_on_401(monkeypatch: pytest.MonkeyPatch):
    class FakeTicker:
        def get_info(self):
            raise Exception(
                'HTTP Error 401: {"finance":{"result":null,"error":{"code":"Unauthorized","description":"User is unable to access this feature"}}}'
            )

    monkeypatch.setattr("src.yahoo_finance.get_ticker", lambda symbol: FakeTicker())

    result = get_info("ABC.NS")

    assert result == {}


def test_yahoo_get_info_returns_empty_dict_on_rate_limit(monkeypatch: pytest.MonkeyPatch):
    class FakeTicker:
        def get_info(self):
            raise Exception("YFRateLimitError('Too Many Requests. Rate limited. Try after a while.')")

    monkeypatch.setattr("src.yahoo_finance.get_ticker", lambda symbol: FakeTicker())

    result = get_info("ABC.NS")

    assert result == {}


def test_invalid_crumb_is_treated_as_recoverable_yahoo_error():
    assert is_recoverable_yahoo_error(Exception("Invalid Crumb"))


def test_relative_liquidity_check_accepts_150_day_history(configured_environment):
    settings = get_settings()
    df = pd.DataFrame(
        {
            "Close": [100.0] * 150,
            "Volume": [10_000] * 150,
        },
        index=pd.date_range("2025-08-01", periods=150, freq="D"),
    )

    is_liquid, reason = RiskAndQualityAnalyzer.relative_liquidity_check(df, settings)

    assert is_liquid
    assert reason is None


def test_scan_stocks_parallel_decays_ranks_even_without_qualifiers(configured_environment, monkeypatch: pytest.MonkeyPatch):
    today = dt.datetime.now(dt.UTC).date()
    with get_db_context() as session:
        session.add(
            MomentumStock(
                symbol="OLD.NS",
                last_seen_date=today - dt.timedelta(days=2),
                rank_score=5,
                daily_rank_delta=0,
                current_price=100.0,
            )
        )

    monkeypatch.setattr("src.services.Bhavcopy.get_bhavcopy_data", lambda: pd.DataFrame())
    monkeypatch.setattr("src.services.MarketValidator.get_expected_market_date", lambda settings_obj: today)
    monkeypatch.setattr(
        "src.services.StockFetcher.process_single_batch",
        lambda batch, batch_id, settings_obj, bhavcopy_df, expected_market_date=None: set(),
    )

    StockFetcher.scan_stocks_parallel(["OLD.NS"], batch_size=1, max_workers=1)

    with get_db_context() as session:
        updated_rank = session.execute(
            select(MomentumStock).where(MomentumStock.symbol == "OLD.NS")
        ).scalar_one().rank_score
    assert updated_rank == 4


def test_update_ranking_sets_last_seen_date_to_today(configured_environment):
    settings = get_settings()
    with get_db_context() as session:
        yesterday = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1)
        session.add(
            MomentumStock(
                symbol="ABC.NS",
                last_seen_date=yesterday,
                rank_score=2,
                daily_rank_delta=0,
                current_price=95.0,
            )
        )

    with get_db_context() as session:
        engine = RankingEngine(session, settings)
        engine.update_ranking(
            symbol="ABC.NS",
            price=110.0,
            low_52_week_price=80.0,
            low_52_week_date=dt.date(2025, 6, 1),
            high_52_week_price=120.0,
            high_52_week_date=dt.date(2026, 3, 28),
            risk_score=2,
            is_volume_confirmed=True,
            is_fundamental_ok=True,
            company_name="ABC Ltd",
        )
        expected_today = engine.today

    with get_db_context() as session:
        last_seen_date = session.execute(
            select(MomentumStock).where(MomentumStock.symbol == "ABC.NS")
        ).scalar_one().last_seen_date
    assert last_seen_date == expected_today


def test_update_ranking_stores_stop_target_and_diversification_fields(configured_environment):
    settings = get_settings()
    with get_db_context() as session:
        engine = RankingEngine(session, settings)
        engine.update_ranking(
            symbol="RISK.NS",
            price=100.0,
            low_52_week_price=70.0,
            low_52_week_date=dt.date(2025, 6, 1),
            high_52_week_price=120.0,
            high_52_week_date=dt.date(2026, 3, 28),
            risk_score=1,
            is_volume_confirmed=True,
            is_fundamental_ok=True,
            stop_loss_price=92.0,
            take_profit_price=115.0,
            stop_loss_pct=-8.0,
            take_profit_pct=15.0,
            sector="Capital Goods",
            cap_band="MID_CAP",
        )

    with get_db_context() as session:
        stock = session.execute(select(MomentumStock).where(MomentumStock.symbol == "RISK.NS")).scalar_one()
        values = {
            "stop_loss_price": stock.stop_loss_price,
            "take_profit_price": stock.take_profit_price,
            "stop_loss_pct": stock.stop_loss_pct,
            "take_profit_pct": stock.take_profit_pct,
            "sector": stock.sector,
            "cap_band": stock.cap_band,
        }

    assert values["stop_loss_price"] == 92.0
    assert values["take_profit_price"] == 115.0
    assert values["stop_loss_pct"] == -8.0
    assert values["take_profit_pct"] == 15.0
    assert values["sector"] == "Capital Goods"
    assert values["cap_band"] == "MID_CAP"


def test_schema_migration_is_idempotent(configured_environment):
    ensure_momentum_schema_columns()
    ensure_momentum_schema_columns()

    with get_engine().connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(momentum_ranks)").fetchall()}

    assert "stop_loss_price" in columns
    assert "take_profit_price" in columns
    assert "sector" in columns
    assert "cap_band" in columns


def test_top_movers_applies_sector_and_small_cap_diversification(configured_environment, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DIVERSIFICATION_ENABLED", "true")
    monkeypatch.setenv("MAX_STOCKS_PER_SECTOR", "2")
    monkeypatch.setenv("MAX_SMALL_CAP_TOP_PICKS", "3")
    get_settings.cache_clear()
    settings = get_settings()
    today = dt.date.today()

    with get_db_context() as session:
        for idx in range(5):
            session.add(
                MomentumStock(
                    symbol=f"DEF{idx}.NS",
                    last_seen_date=today,
                    rank_score=10 - idx,
                    daily_rank_delta=2,
                    risk_score=1,
                    is_volume_confirmed=True,
                    is_fundamental_ok=True,
                    current_price=100.0,
                    sector="Defence",
                    cap_band="SMALL_CAP",
                )
            )
        session.add(
            MomentumStock(
                symbol="BANK.NS",
                last_seen_date=today,
                rank_score=4,
                daily_rank_delta=1,
                risk_score=1,
                is_volume_confirmed=True,
                is_fundamental_ok=True,
                current_price=100.0,
                sector="Banking",
                cap_band="LARGE_CAP",
            )
        )

    with get_db_context() as session:
        selected = StockFetcher.get_top_movers_with_repetition_control(session, settings, today)
        selected_symbols = [stock.symbol for stock in selected]
    assert len([symbol for symbol in selected_symbols if symbol.startswith("DEF")]) == 2
    assert "BANK.NS" in selected_symbols


def test_market_regime_checker_returns_false_when_index_below_sma(configured_environment, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MARKET_REGIME_FILTER_ENABLED", "true")
    get_settings.cache_clear()
    settings = get_settings()
    dates = pd.date_range("2025-01-01", periods=220, freq="D")
    closes = [100.0] * 219 + [80.0]
    df = pd.DataFrame({"Close": closes}, index=dates)

    monkeypatch.setattr("src.services._MARKET_REGIME_CACHE", {})
    monkeypatch.setattr("src.services.download_history", lambda *args, **kwargs: df)

    assert not MarketRegimeChecker.is_bull_market(settings)


def test_market_regime_checker_flattens_multiindex_history(configured_environment, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MARKET_REGIME_FILTER_ENABLED", "true")
    get_settings.cache_clear()
    settings = get_settings()
    dates = pd.date_range("2025-01-01", periods=220, freq="D")
    columns = pd.MultiIndex.from_tuples([("Close", "^NSEI"), ("Volume", "^NSEI")])
    df = pd.DataFrame([[100.0, 1_000]] * 219 + [[120.0, 1_000]], index=dates, columns=columns)

    monkeypatch.setattr("src.services._MARKET_REGIME_CACHE", {})
    monkeypatch.setattr("src.services.download_history", lambda *args, **kwargs: df)

    assert MarketRegimeChecker.is_bull_market(settings)
