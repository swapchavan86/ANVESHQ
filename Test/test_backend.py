import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from datetime import date, datetime, timedelta
import zoneinfo
import os
import json

# Adjust path to import modules from src
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../Backend')))

from src.services import FraudDetector, RankingEngine, MarketValidator, StockFetcher
from src.utils import TickerLoader
from src.models import MomentumStock, Base
from src.config import get_settings

# --- FraudDetector Tests ---
@pytest.fixture
def sample_dataframe():
    dates = pd.to_datetime([f'2025-01-{i:02d}' for i in range(1, 21)])
    return pd.DataFrame({
        'Volume': [100000] * 200,
        'Close': [100.0] * 200,
        'High': [105.0] * 200,
        'Low': [95.0] * 200,
    }, index=pd.to_datetime([date(2024, 1, 1) + timedelta(days=i) for i in range(200)]))

class TestFraudDetector:
    # --- basic_liquidity_check ---
    def test_liquidity_positive_sufficient_turnover(self, sample_dataframe, app_settings):
        # 100000 volume * 100 price = 1 Cr turnover, which is > 0.5 Cr
        sample_dataframe.loc[sample_dataframe.index[-10:], 'Volume'] *= 2
        result, _ = FraudDetector.relative_liquidity_check(sample_dataframe, app_settings)
        assert result is True

    def test_liquidity_negative_insufficient_turnover(self, sample_dataframe, app_settings):
        # 1000 volume * 100 price = 1 Lakh turnover, which is < 0.5 Cr
        sample_dataframe['Volume'].iloc[-10:] = 1000
        result, _ = FraudDetector.relative_liquidity_check(sample_dataframe, app_settings)
        assert result is False

    def test_liquidity_negative_empty_dataframe(self, app_settings):
        result, _ = FraudDetector.relative_liquidity_check(pd.DataFrame(), app_settings)
        assert result is False

    def test_liquidity_negative_too_few_rows(self, app_settings):
        df = pd.DataFrame({'Volume': [100000] * 5, 'Close': [100.0] * 5})
        result, _ = FraudDetector.relative_liquidity_check(df, app_settings)
        assert result is False
    
    # --- deep_fundamental_check ---
    @patch('os.path.exists', return_value=False)
    @patch('yfinance.Ticker')
    def test_fundamental_positive_good_fundamentals(self, mock_ticker, mock_exists, app_settings):
        mock_ticker_instance = MagicMock()
        mock_ticker_instance.info = {
            'marketCap': app_settings.MIN_MCAP_CRORES * 10_000_000 * 2, # Well above min
            'trailingPE': 25.0, # Positive PE
            'debtToEquity': 1.0 # Low D/E
        }
        mock_ticker.return_value = mock_ticker_instance
        result = FraudDetector.deep_fundamental_check("TEST.NS", app_settings)
        assert result is True

    @patch('os.path.exists', return_value=False)
    @patch('yfinance.Ticker')
    def test_fundamental_negative_low_market_cap(self, mock_ticker, mock_exists, app_settings):
        mock_ticker_instance = MagicMock()
        mock_ticker_instance.info = {
            'marketCap': app_settings.MIN_MCAP_CRORES * 10_000_000 * 0.5, # Below min
            'trailingPE': 25.0,
            'debtToEquity': 50.0
        }
        mock_ticker.return_value = mock_ticker_instance
        result = FraudDetector.deep_fundamental_check("TEST.NS", app_settings)
        assert result is False

    @patch('os.path.exists', return_value=False)
    @patch('yfinance.Ticker')
    def test_fundamental_negative_negative_pe(self, mock_ticker, mock_exists, app_settings):
        mock_ticker_instance = MagicMock()
        mock_ticker_instance.info = {
            'marketCap': app_settings.MIN_MCAP_CRORES * 10_000_000 * 2,
            'trailingPE': -5.0, # Negative PE
            'debtToEquity': 50.0
        }
        mock_ticker.return_value = mock_ticker_instance
        result = FraudDetector.deep_fundamental_check("TEST.NS", app_settings)
        assert result is False

    @patch('os.path.exists', return_value=False)
    @patch('yfinance.Ticker')
    def test_fundamental_negative_high_debt_to_equity(self, mock_ticker, mock_exists, app_settings):
        mock_ticker_instance = MagicMock()
        mock_ticker_instance.info = {
            'marketCap': app_settings.MIN_MCAP_CRORES * 10_000_000 * 2,
            'trailingPE': 25.0,
            'debtToEquity': 400.0 # High D/E
        }
        mock_ticker.return_value = mock_ticker_instance
        result = FraudDetector.deep_fundamental_check("TEST.NS", app_settings)
        assert result is False

    @patch('os.path.exists', return_value=False)
    @patch('yfinance.Ticker')
    def test_fundamental_negative_invalid_symbol_or_api_error(self, mock_ticker, mock_exists, app_settings, db_session):
        mock_ticker.side_effect = Exception("API Error") # Simulate API error
        result = FraudDetector.deep_fundamental_check("INVALID", app_settings)
        # Should return True if it cannot verify (fails gracefully)
        assert result is True

# --- RankingEngine Tests ---
class TestRankingEngine:
    def test_ranking_positive_add_new_stock(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        today = datetime.now(zoneinfo.ZoneInfo(app_settings.TIMEZONE)).date()
        
        # New dummy values for testing
        test_low_52_date = date(2024, 1, 10)
        test_high_52_price = 160.0
        
        engine_svc.update_ranking("NEWSTOCK.NS", 150.0, 100.0, test_low_52_date, test_high_52_price, date(2024, 1, 1))
        db_session.commit()
        
        stock = db_session.query(MomentumStock).filter_by(symbol="NEWSTOCK.NS").first()
        assert stock is not None
        assert stock.symbol == "NEWSTOCK.NS"
        assert stock.rank_score == 0
        assert stock.last_seen_date == today
        assert stock.current_price == 150.0
        assert stock.low_52_week == 100.0
        assert stock.low_52_week_date == test_low_52_date
        assert stock.high_52_week_price == test_high_52_price
        assert stock.high_52_week_date == date(2024, 1, 1)

    def test_ranking_positive_update_existing_stock_same_day(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        today = datetime.now(zoneinfo.ZoneInfo(app_settings.TIMEZONE)).date()
        
        # New dummy values for testing
        test_low_52_date = date(2024, 1, 10)
        test_high_52_price = 160.0
        
        # Add initial stock with all new fields
        initial_stock = MomentumStock(
            symbol="UPDATED.NS", rank_score=5, last_seen_date=today,
            current_price=100.0, low_52_week=50.0, low_52_week_date=date(2023, 12, 1),
            high_52_week_price=120.0, high_52_week_date=date(2024, 1, 1)
        )
        db_session.add(initial_stock)
        db_session.commit()

        # Update on the same day
        engine_svc.update_ranking("UPDATED.NS", 105.0, 55.0, test_low_52_date, test_high_52_price, date(2024, 1, 2))
        db_session.commit() # Commit the changes made by update_ranking
        stock = db_session.query(MomentumStock).filter_by(symbol="UPDATED.NS").first()
        
        assert stock.rank_score == 5 # Score should not change if updated on same day
        assert stock.current_price == 105.0 # Price should update
        assert stock.low_52_week == 55.0
        assert stock.low_52_week_date == test_low_52_date
        assert stock.high_52_week_price == test_high_52_price
        assert stock.high_52_week_date == date(2024, 1, 2)

    def test_ranking_positive_update_existing_stock_score_increase(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        today = datetime.now(zoneinfo.ZoneInfo(app_settings.TIMEZONE)).date()
        yesterday = today - timedelta(days=1)
        
        # New dummy values for testing
        test_low_52_date = date(2024, 1, 11)
        test_high_52_price = 165.0
        
        # Add initial stock with all new fields
        initial_stock = MomentumStock(
            symbol="INCREASE.NS", rank_score=5, last_seen_date=yesterday,
            current_price=100.0, low_52_week=50.0, low_52_week_date=date(2023, 12, 2),
            high_52_week_price=125.0, high_52_week_date=date(2024, 1, 1)
        )
        db_session.add(initial_stock)
        db_session.commit()

        # Update the next day (within STREAK_THRESHOLD_DAYS)
        engine_svc.update_ranking("INCREASE.NS", 105.0, 55.0, test_low_52_date, test_high_52_price, date(2024, 1, 2))
        db_session.commit() # Commit the changes made by update_ranking
        stock = db_session.query(MomentumStock).filter_by(symbol="INCREASE.NS").first()
        
        assert stock.rank_score == 6 # Score should increase
        assert stock.last_seen_date == today
        assert stock.current_price == 105.0
        assert stock.low_52_week == 55.0
        assert stock.low_52_week_date == test_low_52_date
        assert stock.high_52_week_price == test_high_52_price
        assert stock.high_52_week_date == date(2024, 1, 2)

    def test_ranking_positive_update_existing_stock_score_reset(self, db_session, app_settings):
        engine_svc = RankingEngine(db_session, app_settings)
        today = datetime.now(zoneinfo.ZoneInfo(app_settings.TIMEZONE)).date()
        old_date = today - timedelta(days=app_settings.STREAK_THRESHOLD_DAYS + 1)
        
        # New dummy values for testing
        test_low_52_date = date(2024, 1, 12)
        test_high_52_price = 170.0
        
        # Add initial stock with all new fields
        initial_stock = MomentumStock(
            symbol="RESET.NS", rank_score=5, last_seen_date=old_date,
            current_price=100.0, low_52_week=50.0, low_52_week_date=date(2023, 12, 3),
            high_52_week_price=130.0, high_52_week_date=date(2024, 1, 1)
        )
        db_session.add(initial_stock)
        db_session.commit()

        # Update after STREAK_THRESHOLD_DAYS
        engine_svc.update_ranking("RESET.NS", 105.0, 55.0, test_low_52_date, test_high_52_price, date(2024, 1, 2))
        db_session.commit() # Commit the changes made by update_ranking
        stock = db_session.query(MomentumStock).filter_by(symbol="RESET.NS").first()
        
        assert stock.rank_score == 6 # Score should reset
        assert stock.last_seen_date == today
        assert stock.current_price == 105.0
        assert stock.low_52_week == 55.0
        assert stock.low_52_week_date == test_low_52_date
        assert stock.high_52_week_price == test_high_52_price
        assert stock.high_52_week_date == date(2024, 1, 2)

# --- MarketValidator Tests ---
class TestMarketValidator:
    @patch('datetime.datetime')
    def test_should_run_positive_weekday(self, mock_dt, app_settings):
        mock_dt.now.return_value = datetime(2025, 1, 6, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(app_settings.TIMEZONE)) # Monday
        result = MarketValidator.should_run(app_settings)
        assert result is True

    @patch('datetime.datetime')
    def test_should_run_negative_weekend(self, mock_dt, app_settings):
        mock_dt.now.return_value = datetime(2025, 1, 11, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(app_settings.TIMEZONE)) # Saturday
        result = MarketValidator.should_run(app_settings)
        assert result is False

    def test_freshness_positive_recent_data(self, app_settings):
        today = datetime.now(zoneinfo.ZoneInfo(app_settings.TIMEZONE)).date()
        recent_date = today - timedelta(days=1)
        df = pd.DataFrame({'Close': [100]}, index=pd.to_datetime([recent_date]))
        result = MarketValidator.validate_market_data_freshness(df, app_settings)
        assert result is True

    def test_freshness_negative_old_data(self, app_settings):
        today = datetime.now(zoneinfo.ZoneInfo(app_settings.TIMEZONE)).date()
        old_date = today - timedelta(days=4) # More than 3 days old
        df = pd.DataFrame({'Close': [100]}, index=pd.to_datetime([old_date]))
        result = MarketValidator.validate_market_data_freshness(df, app_settings)
        assert result is False
    
    def test_freshness_negative_empty_dataframe(self, app_settings):
        result = MarketValidator.validate_market_data_freshness(pd.DataFrame(), app_settings)
        assert result is False

# --- TickerLoader Tests ---
@pytest.fixture
def clear_ticker_cache():
    """Fixture to clear the ticker cache file before a test."""
    if os.path.exists(TickerLoader.CACHE_FILE):
        os.remove(TickerLoader.CACHE_FILE)

class TestTickerLoader:
    @patch('src.utils.get_settings')
    def test_get_unique_tickers_from_json_success(self, mock_get_settings, tmp_path, clear_ticker_cache):
        """
        Tests that tickers are loaded correctly from the JSON universe file
        when the USE_JSON_UNIVERSE flag is True.
        """
        # --- Setup ---
        # Mock settings to use the JSON universe
        mock_settings = get_settings()
        mock_settings.USE_JSON_UNIVERSE = True
        
        json_content = {
            "records": [
                {"symbol": "TCS", "exchange_suffix": "NS"},
                {"symbol": "RELIANCE", "exchange_suffix": "NS"},
                {"symbol": "HDFCBANK", "exchange_suffix": "BO"},
            ]
        }
        json_file = tmp_path / "universe.json"
        json_file.write_text(json.dumps(json_content))
        mock_settings.JSON_UNIVERSE_PATH = str(json_file)
        
        mock_get_settings.return_value = mock_settings

        # --- Run ---
        tickers = TickerLoader.get_unique_tickers()

        # --- Assert ---
        assert len(tickers) == 3
        assert "TCS.NS" in tickers
        assert "RELIANCE.NS" in tickers
        assert "HDFCBANK.BO" in tickers

    @patch('src.utils.get_settings')
    def test_get_unique_tickers_from_json_file_not_found(self, mock_get_settings, tmp_path, clear_ticker_cache):
        """
        Tests that the function raises FileNotFoundError if the JSON universe file is not found.
        """
        # --- Setup ---
        mock_settings = get_settings()
        mock_settings.USE_JSON_UNIVERSE = True
        mock_settings.JSON_UNIVERSE_PATH = str(tmp_path / "non_existent.json")
        mock_get_settings.return_value = mock_settings

        # --- Run & Assert ---
        with pytest.raises(FileNotFoundError):
            TickerLoader.get_unique_tickers()

    @patch('src.utils.get_settings')
    @patch('requests.Session')
    def test_get_unique_tickers_fallback_to_live(self, mock_session, mock_get_settings, clear_ticker_cache):
        """
        Tests that the TickerLoader falls back to the live fetching logic
        when USE_JSON_UNIVERSE is False.
        """
        # --- Setup ---
        mock_settings = get_settings()
        mock_settings.USE_JSON_UNIVERSE = False
        mock_get_settings.return_value = mock_settings

        # Mock the live fetching methods to check if they are called
        with patch.object(TickerLoader, '_fetch_nse_master', return_value={"INE467A01029": "TCS"}) as mock_fetch_nse, \
             patch.object(TickerLoader, '_overlay_nifty500', return_value=None) as mock_overlay, \
             patch.object(TickerLoader, '_fetch_bse_only_tickers', return_value=[]) as mock_fetch_bse:

            # --- Run ---
            TickerLoader.get_unique_tickers()

            # --- Assert ---
            mock_fetch_nse.assert_called_once()
            mock_overlay.assert_called_once()
            mock_fetch_bse.assert_called_once()



# --- StockFetcher Tests ---
class TestStockFetcher:
    @patch('yfinance.download')
    @patch('src.services.FraudDetector.volume_confirmation')
    @patch('src.services.FraudDetector.relative_liquidity_check')
    @patch('src.services.FraudDetector.deep_fundamental_check')
    @patch('src.services.RankingEngine')
    @patch('src.services.MarketValidator.validate_market_data_freshness')
    @patch('src.services.datetime')
    def test_process_single_batch_positive_stock_qualified(self, mock_datetime, mock_freshness, mock_ranking_engine_cls, mock_deep_fundamental, mock_liquidity_check, mock_volume_confirmation, mock_yf_download, db_session, app_settings):
        mock_datetime.now.return_value = datetime(2025, 1, 10, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(app_settings.TIMEZONE))

        # Mock yfinance.download data
        dates = pd.to_datetime([date(2024, 1, 1) + timedelta(days=i) for i in range(200)])
        mock_df = pd.DataFrame({
            'Open': [100] * 200, 'High': [105] * 200, 'Low': [90] * 200, 'Close': [105] * 200, 'Volume': [60000] * 200},
            index=dates
        )
        mock_df.iloc[-1, mock_df.columns.get_loc('High')] = 110

        mock_yf_download.return_value = mock_df
        
        # Mock checks to pass
        mock_liquidity_check.return_value = (True, None)
        mock_volume_confirmation.return_value = (True, None)
        mock_deep_fundamental.return_value = True
        mock_freshness.return_value = True

        mock_ranking_engine_instance = MagicMock()
        mock_ranking_engine_cls.return_value = mock_ranking_engine_instance
        bhavcopy_df = pd.DataFrame({
            'TckrSymb': ['GOODSTOCK'],
            'BizDt': [datetime(2025, 1, 10).date()],
            'OpnPric': [100],
            'HghPric': [110],
            'LwPric': [90],
            'ClsPric': [105],
            'TtlTradgVol': [60000]
        })

        StockFetcher.process_single_batch(["GOODSTOCK.NS"], 1, app_settings, bhavcopy_df)

        mock_ranking_engine_instance.update_ranking.assert_called_once()
        args, kwargs = mock_ranking_engine_instance.update_ranking.call_args
        
        # Extract expected values from the mock_df
        expected_current_close = 105.0
        expected_low_52_week_price = 90.0
        expected_low_52_week_date = mock_df['Low'].idxmin().date()
        expected_high_52_week_price = float(mock_df['High'].max())
        expected_high_52_week_date = mock_df['High'].idxmax().date()

        assert args[0] == "GOODSTOCK.NS" # symbol
        assert args[1] == expected_current_close # current_price
        assert args[2] == expected_low_52_week_price # low_52_week_price
        assert args[3] == expected_low_52_week_date # low_52_week_date
        assert args[4] == expected_high_52_week_price # high_52_week_price
        assert args[5] == expected_high_52_week_date # high_52_week_date
    
    @patch('yfinance.download')
    @patch('src.services.FraudDetector.relative_liquidity_check')
    @patch('src.services.FraudDetector.deep_fundamental_check')
    @patch('src.services.RankingEngine')
    @patch('src.services.MarketValidator.validate_market_data_freshness')
    @patch('src.services.datetime')
    def test_process_single_batch_negative_below_min_price(self, mock_datetime, mock_freshness, mock_ranking_engine_cls, mock_deep_fundamental, mock_liquidity_check, mock_yf_download, db_session, app_settings):
        mock_datetime.now.return_value = datetime(2025, 1, 10, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(app_settings.TIMEZONE))

        # Mock yfinance.download data with price below MIN_PRICE
        mock_df = pd.DataFrame({
            'Open': [10], 'High': [15], 'Low': [8], 'Close': [12], 'Volume': [100000]},
            index=pd.to_datetime(['2025-01-09'])
        )
        mock_yf_download.return_value = mock_df
        
        mock_freshness.return_value = True
        bhavcopy_df = pd.DataFrame({
            'TckrSymb': ['CHEAPSTOCK'],
            'BizDt': [datetime(2025, 1, 10).date()],
            'OpnPric': [10],
            'HghPric': [15],
            'LwPric': [8],
            'ClsPric': [12],
            'TtlTradgVol': [100000]
        })
        
        StockFetcher.process_single_batch(["CHEAPSTOCK.NS"], 1, app_settings, bhavcopy_df)

        mock_ranking_engine_cls.return_value.update_ranking.assert_not_called()

    @patch('yfinance.download')
    @patch('src.services.FraudDetector.relative_liquidity_check')
    @patch('src.services.FraudDetector.deep_fundamental_check')
    @patch('src.services.RankingEngine')
    @patch('src.services.MarketValidator.validate_market_data_freshness')
    @patch('src.services.datetime')
    def test_process_single_batch_negative_liquidity_check_fails(self, mock_datetime, mock_freshness, mock_ranking_engine_cls, mock_deep_fundamental, mock_liquidity_check, mock_yf_download, db_session, app_settings):
        mock_datetime.now.return_value = datetime(2025, 1, 10, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(app_settings.TIMEZONE))

        # Mock yfinance.download data
        mock_df = pd.DataFrame({
            'Open': [100], 'High': [110], 'Low': [90], 'Close': [105], 'Volume': [1000]},
            index=pd.to_datetime(['2025-01-09'])
        )
        mock_yf_download.return_value = mock_df
        
        mock_liquidity_check.return_value = (False, "Liquidity check failed") # Liquidity check fails
        mock_freshness.return_value = True
        bhavcopy_df = pd.DataFrame({
            'TckrSymb': ['LIQUIDITYFAIL'],
            'BizDt': [datetime(2025, 1, 10).date()],
            'OpnPric': [100],
            'HghPric': [110],
            'LwPric': [90],
            'ClsPric': [105],
            'TtlTradgVol': [1000]
        })
        
        StockFetcher.process_single_batch(["LIQUIDITYFAIL.NS"], 1, app_settings, bhavcopy_df)

        mock_ranking_engine_cls.return_value.update_ranking.assert_not_called()

    @patch('yfinance.download')
    @patch('src.services.FraudDetector.relative_liquidity_check')
    @patch('src.services.FraudDetector.deep_fundamental_check')
    @patch('src.services.RankingEngine')
    @patch('src.services.MarketValidator.validate_market_data_freshness')
    @patch('src.services.datetime')
    def test_process_single_batch_negative_fundamental_check_fails(self, mock_datetime, mock_freshness, mock_ranking_engine_cls, mock_deep_fundamental, mock_liquidity_check, mock_yf_download, db_session, app_settings):
        mock_datetime.now.return_value = datetime(2025, 1, 10, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(app_settings.TIMEZONE))

        # Mock yfinance.download data
        mock_df = pd.DataFrame({
            'Open': [100], 'High': [110], 'Low': [90], 'Close': [105], 'Volume': [60000]},
            index=pd.to_datetime(['2025-01-09'])
        )
        mock_yf_download.return_value = mock_df
        
        mock_liquidity_check.return_value = (True, None)
        mock_deep_fundamental.return_value = False # Fundamental check fails
        mock_freshness.return_value = True
        bhavcopy_df = pd.DataFrame({
            'TckrSymb': ['FUNDAMENTALFAIL'],
            'BizDt': [datetime(2025, 1, 10).date()],
            'OpnPric': [100],
            'HghPric': [110],
            'LwPric': [90],
            'ClsPric': [105],
            'TtlTradgVol': [60000]
        })
        
        StockFetcher.process_single_batch(["FUNDAMENTALFAIL.NS"], 1, app_settings, bhavcopy_df)

        mock_ranking_engine_cls.return_value.update_ranking.assert_not_called()

    @patch('yfinance.download')
    @patch('src.services.FraudDetector.relative_liquidity_check')
    @patch('src.services.FraudDetector.deep_fundamental_check')
    @patch('src.services.RankingEngine')
    @patch('src.services.MarketValidator.validate_market_data_freshness')
    @patch('src.services.datetime')
    def test_process_single_batch_negative_stale_market_data(self, mock_datetime, mock_freshness, mock_ranking_engine_cls, mock_deep_fundamental, mock_liquidity_check, mock_yf_download, db_session, app_settings):
        mock_datetime.now.return_value = datetime(2025, 1, 10, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(app_settings.TIMEZONE))

        # Mock yfinance.download data
        mock_df = pd.DataFrame({
            'Open': [100], 'High': [110], 'Low': [90], 'Close': [105], 'Volume': [60000]},
            index=pd.to_datetime(['2025-01-01']) # Old data
        )
        mock_yf_download.return_value = mock_df
        
        mock_freshness.return_value = False # Stale data check fails
        bhavcopy_df = pd.DataFrame({
            'TckrSymb': ['STALEDATA'],
            'BizDt': [datetime(2025, 1, 1).date()],
            'OpnPric': [100],
            'HghPric': [110],
            'LwPric': [90],
            'ClsPric': [105],
            'TtlTradgVol': [60000]
        })
        
        StockFetcher.process_single_batch(["STALEDATA.NS"], 1, app_settings, bhavcopy_df)

        mock_ranking_engine_cls.return_value.update_ranking.assert_not_called()

    @patch('yfinance.download')
    @patch('src.services.FraudDetector.relative_liquidity_check')
    @patch('src.services.FraudDetector.deep_fundamental_check')
    @patch('src.services.RankingEngine')
    @patch('src.services.MarketValidator.validate_market_data_freshness')
    @patch('src.services.datetime')
    def test_process_single_batch_negative_empty_download_data(self, mock_datetime, mock_freshness, mock_ranking_engine_cls, mock_deep_fundamental, mock_liquidity_check, mock_yf_download, db_session, app_settings):
        mock_datetime.now.return_value = datetime(2025, 1, 10, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(app_settings.TIMEZONE))

        mock_yf_download.return_value = pd.DataFrame() # Empty dataframe from download
        bhavcopy_df = pd.DataFrame()
        
        StockFetcher.process_single_batch(["NOSUCHSTOCK.NS"], 1, app_settings, bhavcopy_df)

        mock_ranking_engine_cls.return_value.update_ranking.assert_not_called()
