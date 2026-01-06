"""
This script is responsible for building a stable, versioned reference universe of stocks.
It fetches data from multiple sources in a tiered approach to ensure robustness and coverage.
The output is a versioned JSON file that serves as the master list for the daily momentum scanner.
This process is designed to be run weekly to avoid daily dependencies on live, potentially unstable,
data sources.
"""
import os
import pandas as pd
import requests
import json
from datetime import datetime
from io import StringIO
import logging
from src.config import get_settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define the directory to store the master data files.
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'master')
SNAPSHOT_FILENAME_TEMPLATE = "master-{}.json"
LATEST_FILENAME = "master-latest.json"

def get_bse_equity_list(url: str):
    """
    Fetches the list of equity scrips from the BSE website.
    This function will need to be implemented with a scraping library like BeautifulSoup
    as the data is not available as a direct CSV download.
    For now, it returns an empty DataFrame.
    """
    logging.info("Fetching BSE CM list... (scrapping required, returning empty for now)")
    # Placeholder for BSE scraping logic
    # response = requests.get(url)
    # soup = BeautifulSoup(response.content, 'html.parser')
    # ... scraping logic ...
    return pd.DataFrame(columns=['ISIN', 'Symbol', 'Security Name'])


def master_data_builder():
    """
    Builds a stable, versioned reference universe from multiple sources.
    The logic is tiered to prioritize the most reliable sources.
    
    Tier 1: NSE Equity Master - The primary source of truth for all NSE-listed equities.
    Tier 2: NIFTY 500 - A stability anchor to ensure major stocks are included if missed in Tier 1.
    Tier 3: BSE CM List - For expansion to include stocks not listed on NSE.
    
    The final output is a JSON file with a timestamped snapshot and a 'latest' alias.
    """
    logging.info("Starting master data builder job.")
    settings = get_settings()

    # Create data directory if it doesn't exist. This is where the JSON files will be stored.
    os.makedirs(DATA_DIR, exist_ok=True)

    # --- Tier 1: NSE Equity Master ---
    # This is the primary and most critical source. If this fails, the job aborts.
    logging.info(f"Fetching Tier 1 data from {settings.NSE_EQUITY_LIST_URL}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(settings.NSE_EQUITY_LIST_URL, headers=headers)
        response.raise_for_status()
        nse_master_df = pd.read_csv(StringIO(response.text))
        # Clean up column names and filter for 'EQ' series only.
        nse_master_df.columns = nse_master_df.columns.str.strip()
        nse_master_df = nse_master_df[nse_master_df['SERIES'] == 'EQ']
        # Standardize column names and add metadata.
        nse_master_df.rename(columns={'ISIN NUMBER': 'isin', 'SYMBOL': 'symbol'}, inplace=True)
        nse_master_df['exchange'] = 'NSE'
        nse_master_df['exchange_suffix'] = 'NS'
        nse_master_df['tier'] = 'TIER_1'
        nse_master_df = nse_master_df[['isin', 'symbol', 'exchange', 'exchange_suffix', 'tier']]
        logging.info(f"Successfully fetched and processed {len(nse_master_df)} Tier 1 records.")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch NSE Equity Master: {e}")
        return # Abort job on failure

    # --- Tier 2: NIFTY 500 ---
    # This is a secondary source to ensure the most important stocks are included.
    # Failure is not critical; the job will continue without it.
    logging.info(f"Fetching Tier 2 data from {settings.NSE_NIFTY500_CSV_URL}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(settings.NSE_NIFTY500_CSV_URL, headers=headers)
        response.raise_for_status()
        nifty_500_df = pd.read_csv(StringIO(response.text))
        nifty_500_df.columns = nifty_500_df.columns.str.strip()
        nifty_500_df.rename(columns={'ISIN Code': 'isin', 'Symbol': 'symbol'}, inplace=True)
        nifty_500_df['exchange'] = 'NSE'
        nifty_500_df['exchange_suffix'] = 'NS'
        nifty_500_df['tier'] = 'TIER_2'
        nifty_500_df = nifty_500_df[['isin', 'symbol', 'exchange', 'exchange_suffix', 'tier']]
        logging.info(f"Successfully fetched and processed {len(nifty_500_df)} Tier 2 records.")
    except requests.exceptions.RequestException as e:
        logging.warning(f"Failed to fetch NIFTY 500 list: {e}. Continuing without it.")
        nifty_500_df = pd.DataFrame()

    # --- Tier 3: BSE CM list ---
    # This source is for expansion and is currently a placeholder.
    # bse_df = get_bse_equity_list(settings.BSE_CM_CSV_URL) # Placeholder for now
    bse_df = pd.DataFrame()


    # --- Combine and Deduplicate ---
    # The dataframes are concatenated, and duplicates are removed based on the ISIN,
    # which is the canonical identifier. Tier 1 is prioritized.
    combined_df = pd.concat([nse_master_df, nifty_500_df], ignore_index=True)
    combined_df.drop_duplicates(subset=['isin'], keep='first', inplace=True)
    
    # Logic to add BSE stocks if they are not already present from NSE sources.
    if not bse_df.empty:
        bse_df = bse_df[~bse_df['isin'].isin(combined_df['isin'])]
        bse_df['exchange'] = 'BSE'
        bse_df['exchange_suffix'] = 'BO'
        bse_df['tier'] = 'TIER_3'
        combined_df = pd.concat([combined_df, bse_df], ignore_index=True)


    # --- Prepare Final JSON Output ---
    # The final dataframe is converted to a list of records and wrapped in a JSON object
    # with metadata about the snapshot.
    output_records = combined_df.to_dict(orient='records')
    snapshot_date = datetime.now().strftime("%Y-%m-%d")
    output_json = {
        "snapshot_date": snapshot_date,
        "source": "NSE/BSE",
        "records": output_records
    }

    # Save a timestamped snapshot of the master list.
    snapshot_filepath = os.path.join(DATA_DIR, SNAPSHOT_FILENAME_TEMPLATE.format(snapshot_date))
    with open(snapshot_filepath, 'w') as f:
        json.dump(output_json, f, indent=2)
    logging.info(f"Saved snapshot to {snapshot_filepath}")

    # Create/overwrite the 'latest' alias for the daily scanner to use.
    latest_filepath = os.path.join(DATA_DIR, LATEST_FILENAME)
    with open(latest_filepath, 'w') as f:
        json.dump(output_json, f, indent=2)
    logging.info(f"Saved latest alias to {latest_filepath}")

    logging.info("Master data builder job finished successfully.")


if __name__ == "__main__":
    master_data_builder()

