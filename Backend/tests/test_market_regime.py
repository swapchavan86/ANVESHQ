import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src import services
from src.config import get_settings
from src.services import MarketRegimeChecker


@pytest.fixture
def clear_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MODE", "TEST")
    monkeypatch.setenv("MARKET_REGIME_FILTER_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(services, "_regime_cache", {})
    monkeypatch.setattr(services, "_MARKET_REGIME_CACHE", services._regime_cache)
    yield
    get_settings.cache_clear()


def _history(latest_close: float) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=220, freq="D")
    return pd.DataFrame({"Close": [100.0] * 219 + [latest_close]}, index=dates)


def test_is_bull_market_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MODE", "TEST")
    monkeypatch.setenv("MARKET_REGIME_FILTER_ENABLED", "false")
    get_settings.cache_clear()

    assert MarketRegimeChecker.is_bull_market(get_settings()) is True


def test_is_bull_market_above_sma(clear_settings, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.services.download_history", lambda *args, **kwargs: _history(120.0))

    assert MarketRegimeChecker.is_bull_market(get_settings()) is True


def test_is_bull_market_below_sma(clear_settings, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.services.download_history", lambda *args, **kwargs: _history(80.0))

    assert MarketRegimeChecker.is_bull_market(get_settings()) is False


def test_is_bull_market_cached(clear_settings, monkeypatch: pytest.MonkeyPatch):
    calls = {"count": 0}

    def fake_download(*args, **kwargs):
        calls["count"] += 1
        return _history(120.0)

    monkeypatch.setattr("src.services.download_history", fake_download)

    assert MarketRegimeChecker.is_bull_market(get_settings()) is True
    assert MarketRegimeChecker.is_bull_market(get_settings()) is True
    assert calls["count"] == 1


def test_is_bull_market_yfinance_failure(clear_settings, monkeypatch: pytest.MonkeyPatch):
    def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("src.services.download_history", fail)

    assert MarketRegimeChecker.is_bull_market(get_settings()) is True
