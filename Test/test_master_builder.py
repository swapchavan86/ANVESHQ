import os
import json
import pytest
import requests
from unittest.mock import patch, MagicMock
from src.master_builder import master_data_builder, DATA_DIR, SNAPSHOT_FILENAME_TEMPLATE, LATEST_FILENAME
import pandas as pd
from io import StringIO
from datetime import datetime

# Sample data for mocking API calls
NSE_EQUITY_MASTER_CSV = """
SYMBOL,ISIN NUMBER,SERIES
TCS,INE467B01029,EQ
RELIANCE,INE002A01018,EQ
HDFCBANK,INE040A01034,EQ
"""

NIFTY_500_CSV = """
Symbol,ISIN Code
INFY,INE009A01021
WIPRO,INE075A01022
"""

@pytest.fixture(autouse=True)
def cleanup_files():
    """Fixture to clean up generated files before and after each test."""
    # Before test
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    
    for item in os.listdir(DATA_DIR):
        if item.endswith(".json"):
            os.remove(os.path.join(DATA_DIR, item))
            
    yield
    
    # After test
    for item in os.listdir(DATA_DIR):
        if item.endswith(".json"):
            os.remove(os.path.join(DATA_DIR, item))


@patch('requests.get')
def test_master_data_builder_success(mock_get):
    """
    Tests the successful execution of the master_data_builder function,
    ensuring it fetches data from all tiers, processes it, and creates the
    correct JSON output files.
    """
    # --- Mock API responses ---
    mock_nse_response = MagicMock()
    mock_nse_response.status_code = 200
    mock_nse_response.text = NSE_EQUITY_MASTER_CSV
    
    mock_nifty_response = MagicMock()
    mock_nifty_response.status_code = 200
    mock_nifty_response.text = NIFTY_500_CSV

    # Configure the side_effect to return different responses based on URL
    def get_side_effect(url, headers):
        if "EQUITY_L.csv" in url:
            return mock_nse_response
        elif "ind_nifty500list.csv" in url:
            return mock_nifty_response
        return MagicMock(status_code=404)

    mock_get.side_effect = get_side_effect

    # --- Run the function ---
    master_data_builder()

    # --- Assertions ---
    snapshot_date = datetime.now().strftime("%Y-%m-%d")
    snapshot_filename = SNAPSHOT_FILENAME_TEMPLATE.format(snapshot_date)
    snapshot_filepath = os.path.join(DATA_DIR, snapshot_filename)
    latest_filepath = os.path.join(DATA_DIR, LATEST_FILENAME)

    # 1. Check if both files were created
    assert os.path.exists(snapshot_filepath)
    assert os.path.exists(latest_filepath)

    # 2. Check the content of the 'latest' file
    with open(latest_filepath, 'r') as f:
        data = json.load(f)

    assert data['snapshot_date'] == snapshot_date
    assert data['source'] == "NSE/BSE"
    
    records = data['records']
    assert len(records) == 5 # 3 from NSE + 2 from Nifty500

    # 3. Verify ISIN-based deduplication and tiering
    symbols = {r['symbol']: r['tier'] for r in records}
    assert symbols['TCS'] == 'TIER_1'
    assert symbols['RELIANCE'] == 'TIER_1'
    assert symbols['HDFCBANK'] == 'TIER_1'
    assert symbols['INFY'] == 'TIER_2'
    assert symbols['WIPRO'] == 'TIER_2'
    
@patch('requests.get')
def test_master_data_builder_nse_failure(mock_get):
    """
    Tests that the job aborts gracefully if the Tier 1 (NSE Master)
    fetch fails.
    """
    # --- Mock API failure for NSE ---
    mock_get.side_effect = requests.exceptions.RequestException("Connection Error")

    # --- Run the function ---
    master_data_builder()

    # --- Assertions ---
    # No files should be created if the mandatory Tier 1 source fails
    assert not os.listdir(DATA_DIR)

@patch('requests.get')
def test_master_data_builder_nifty500_failure(mock_get):
    """
    Tests that the job continues execution and generates a file
    even if the Tier 2 (Nifty 500) fetch fails.
    """
    # --- Mock successful NSE response and failed Nifty 500 response ---
    mock_nse_response = MagicMock()
    mock_nse_response.status_code = 200
    mock_nse_response.text = NSE_EQUITY_MASTER_CSV
    
    def get_side_effect(url, headers):
        if "EQUITY_L.csv" in url:
            return mock_nse_response
        elif "ind_nifty500list.csv" in url:
            raise requests.exceptions.RequestException("Not Found")
        return MagicMock(status_code=404)

    mock_get.side_effect = get_side_effect
    
    # --- Run the function ---
    master_data_builder()
    
    # --- Assertions ---
    latest_filepath = os.path.join(DATA_DIR, LATEST_FILENAME)
    assert os.path.exists(latest_filepath)
    
    with open(latest_filepath, 'r') as f:
        data = json.load(f)
        
    # Should only contain Tier 1 data
    assert len(data['records']) == 3
    assert all(r['tier'] == 'TIER_1' for r in data['records'])

