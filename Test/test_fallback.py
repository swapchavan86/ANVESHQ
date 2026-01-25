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

from src.services import RiskAndQualityAnalyzer
from src.config import get_settings

@pytest.fixture
def app_settings():
    # Clear cache before each test
    if os.path.exists("fundamentals_cache.json"):
        os.remove("fundamentals_cache.json")
    return get_settings()

class TestFallbackMechanism:

    @patch('src.services.RiskAndQualityAnalyzer.get_fundamentals_from_google_finance')
    @patch('yfinance.Ticker')
    def test_yfinance_fails_fallback_succeeds(self, mock_yf_ticker, mock_scraper, app_settings):
        # Arrange
        mock_yf_ticker.side_effect = Exception("yfinance fails!")
        mock_scraper.return_value = {'marketCap': 20000000000, 'trailingPE': 25}
        
        # Act
        result = RiskAndQualityAnalyzer.deep_fundamental_check("ANYTICKER.NS", app_settings)
        
        # Assert
        mock_scraper.assert_called_once_with("ANYTICKER.NS")
        assert result is True # Should not be filtered based on the mocked scraper data

    @patch('src.services.RiskAndQualityAnalyzer.get_fundamentals_from_google_finance')
    @patch('yfinance.Ticker')
    def test_yfinance_fails_fallback_also_fails(self, mock_yf_ticker, mock_scraper, app_settings):
        # Arrange
        mock_yf_ticker.side_effect = Exception("yfinance fails!")
        mock_scraper.side_effect = Exception("Scraper fails!")
        
        # Act
        result = RiskAndQualityAnalyzer.deep_fundamental_check("ANYTICKER.NS", app_settings)
        
        # Assert
        mock_scraper.assert_called_once_with("ANYTICKER.NS")
        assert result is True # Fail open

    @patch('requests.get')
    def test_google_finance_scraper_parsing(self, mock_requests_get):
        # Arrange
        # This HTML structure is a simplified representation of Google Finance's layout
        # The key is a div with the label, and the value is in the next sibling div.
        sample_html = """
        <html>
        <body>
            <div>Some other content</div>
            <div class="gyH2C">Market cap</div>
            <div class="P6K39c">₹8.34T</div>
            <div class="gyH2C">P/E ratio</div>
            <div class="P6K39c">25.00</div>
            <div class="gyH2C">Some other stat</div>
            <div class="P6K39c">Some other value</div>
        </body>
        </html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = sample_html
        mock_requests_get.return_value = mock_response

        # Act
        result = RiskAndQualityAnalyzer.get_fundamentals_from_google_finance("ANYTICKER.NS")

        # Assert
        assert result is not None
        assert result['marketCap'] == 8.34e12
        assert result['trailingPE'] == 25.0
