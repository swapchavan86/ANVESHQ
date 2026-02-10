import pandas as pd
import requests
import io
import logging
import os
import datetime
import zipfile
import json
import re
from src.config import get_settings

logger = logging.getLogger("DataUtils")

class TickerLoader:
    CACHE_FILE = "universe_cache.txt"
    
    @staticmethod
    def get_headers():
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

    @staticmethod
    def _fetch_nse_master(session: requests.Session, url: str) -> dict[str, str]:
        """Tier 1: Fetches all tradable equity symbols from the NSE master list."""
        nse_map = {}
        try:
            logger.info(f"Fetching Tier 1 NSE Master List from: {url}")
            response = session.get(url, timeout=30)
            response.raise_for_status()
            
            df = pd.read_csv(io.StringIO(response.content.decode('utf-8')))
            df.columns = [c.strip() for c in df.columns]
            
            # Filter for Equity series and valid symbols
            equity_df = df[df['SERIES'] == 'EQ']
            for _, row in equity_df.iterrows():
                isin = row.get('ISIN NUMBER')
                symbol = row.get('SYMBOL')
                if isin and symbol:
                    nse_map[isin] = symbol
            logger.info(f"Loaded {len(nse_map)} symbols from NSE Master List.")
        except Exception as e:
            logger.critical(f"CRITICAL: NSE Master List (Tier 1) Fetch Failed: {e}. Aborting.")
            raise e # Abort job if this fails
        return nse_map

    @staticmethod
    def _overlay_nifty500(session: requests.Session, url: str, nse_map: dict[str, str]):
        """Tier 2: Overlays Nifty 500 symbols for stability anchor."""
        try:
            logger.info(f"Fetching Tier 2 Nifty 500 Overlay from: {url}")
            response = session.get(url, timeout=15)
            response.raise_for_status()
            
            df = pd.read_csv(io.StringIO(response.content.decode('utf-8')))
            df.columns = [c.strip() for c in df.columns]
            
            count = 0
            for _, row in df.iterrows():
                isin = row.get('ISIN Code')
                symbol = row.get('Symbol')
                if isin and symbol and isin not in nse_map:
                    nse_map[isin] = symbol # Add if not already present
                    count += 1
            logger.info(f"Overlayed {count} new symbols from Nifty 500.")
        except Exception as e:
            logger.warning(f"Nifty 500 Overlay (Tier 2) Failed: {e}")

    @staticmethod
    def _fetch_bse_only_tickers(session: requests.Session, url: str, nse_map: dict[str, str]) -> list[str]:
        """Tier 3: Fetches BSE symbols for coverage expansion, excluding duplicates."""
        bse_tickers = []
        try:
            logger.info(f"Fetching Tier 3 BSE List for expansion from: {url}")
            response = session.get(url, timeout=30)
            response.raise_for_status()

            df = pd.read_csv(io.StringIO(response.content.decode('utf-8')), dtype=str)
            if not df.empty:
                df.columns = [c.strip() for c in df.columns]
                isin_col = TickerLoader._pick_column(df.columns, ["isin", "isinno", "isinnumber", "isincode"])
                symbol_col = TickerLoader._pick_column(df.columns, ["symbol", "securityid", "scripid"])
                code_col = TickerLoader._pick_column(df.columns, ["securitycode", "scripcode", "code"])

                if isin_col and (symbol_col or code_col):
                    selected_col = code_col or symbol_col
                    for _, row in df.iterrows():
                        isin = str(row.get(isin_col, "")).strip()
                        if not isin or isin in nse_map:
                            continue
                        symbol_value = str(row.get(selected_col, "")).strip()
                        if not symbol_value:
                            continue
                        if symbol_value.endswith(".0"):
                            symbol_value = symbol_value[:-2]
                        bse_tickers.append(f"{symbol_value}.BO")
                    logger.info(f"Found {len(bse_tickers)} stocks exclusive to BSE for expansion.")
                    return bse_tickers

            logger.warning("BSE list does not expose expected columns. Falling back to heuristic parser.")
            fallback_df = pd.read_csv(io.StringIO(response.content.decode('utf-8')), header=None, dtype=str)
            for _, row in fallback_df.iterrows():
                isin, scrip_code = None, None
                for val in row.values:
                    val_str = str(val).strip()
                    if not isin and (val_str.startswith("INE") or val_str.startswith("INF")):
                        isin = val_str
                    elif not scrip_code and val_str.isdigit() and len(val_str) == 6:
                        scrip_code = val_str
                if isin and scrip_code and isin not in nse_map:
                    bse_tickers.append(f"{scrip_code}.BO")
            logger.info(f"Found {len(bse_tickers)} stocks exclusive to BSE for expansion.")
        except Exception as e:
            logger.warning(f"BSE Fetch (Tier 3) Failed: {e}")
        return bse_tickers

    @staticmethod
    def _normalize_column_name(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.strip().lower())

    @staticmethod
    def _pick_column(columns: list[str], candidates: list[str]) -> str | None:
        normalized = {TickerLoader._normalize_column_name(c): c for c in columns}
        for candidate in candidates:
            if candidate in normalized:
                return normalized[candidate]
        return None

    @staticmethod
    def _load_from_json(json_path: str) -> list[str]:
        """
        Loads the universe of tickers from a master JSON file.
        This is the new, preferred method for loading the universe, as it relies on a stable,
        pre-built list rather than a live daily feed.

        Args:
            json_path: The path to the master JSON file.

        Returns:
            A list of tickers.
            
        Raises:
            FileNotFoundError: If the JSON file cannot be found at the specified path.
            Exception: For any other errors during file loading or parsing.
        """
        try:
            logger.info(f"Loading universe from JSON file: {json_path}")
            with open(json_path, 'r') as f:
                data = json.load(f)
            
            records = data.get('records', [])
            tickers = []
            for record in records:
                symbol = record.get('symbol')
                exchange_suffix = record.get('exchange_suffix')
                if symbol and exchange_suffix:
                    tickers.append(f"{symbol}.{exchange_suffix}")
            
            logger.info(f"Loaded {len(tickers)} tickers from {json_path}")
            return tickers
        except FileNotFoundError:
            logger.critical(f"CRITICAL: JSON universe file not found at {json_path}. Aborting.")
            raise
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to load or parse JSON universe file: {e}. Aborting.")
            raise
            
    @staticmethod
    def get_unique_tickers() -> list[str]:
        """
        Constructs the stock universe and caches it for the day.
        
        This method now supports two modes of operation, controlled by the
        `USE_JSON_UNIVERSE` setting in `config.py`:
        
        1. JSON Mode (USE_JSON_UNIVERSE = True):
           - Loads tickers from a pre-built master JSON file. This is the default
             and recommended mode for stability and reproducibility.
             
        2. Live Mode (USE_JSON_UNIVERSE = False):
           - Fetches the universe from live NSE and BSE feeds using a 3-tier
             approach. This is the legacy method and should be used with caution due
             to its reliance on potentially unstable external resources.
             
        The resulting list of tickers is cached to a local file for the day to
        avoid repeated lookups.
        """
        if os.path.exists(TickerLoader.CACHE_FILE):
            if datetime.date.fromtimestamp(os.path.getmtime(TickerLoader.CACHE_FILE)) == datetime.date.today():
                logger.info(f"Loading tickers from today's cache: {TickerLoader.CACHE_FILE}")
                with open(TickerLoader.CACHE_FILE, "r") as f:
                    return [line.strip() for line in f if line.strip()]

        logger.info("Cache outdated or not found. Fetching fresh stock universe...")
        settings = get_settings()

        # Depending on the config flag, load from JSON or fetch from live sources.
        if settings.USE_JSON_UNIVERSE:
            # WHY: This is the new, preferred path for loading the universe.
            # It relies on the stable, weekly-built JSON file, which eliminates
            # the operational risk of hitting the live NSE master feed daily.
            final_list = TickerLoader._load_from_json(settings.JSON_UNIVERSE_PATH)
        else:
            # WHY: This is the legacy path, retained for backward compatibility or
            # as a fallback. It hits the live feeds directly.
            try:
                with requests.Session() as session:
                    session.headers.update(TickerLoader.get_headers())
                    
                    # Tier 1 (Mandatory)
                    nse_map = TickerLoader._fetch_nse_master(session, settings.NSE_EQUITY_LIST_URL)
                    
                    # Tier 2 (Optional Overlay)
                    TickerLoader._overlay_nifty500(session, settings.NSE_NIFTY500_CSV_URL, nse_map)
                    
                    # Tier 3 (Optional Expansion)
                    bse_only_tickers = TickerLoader._fetch_bse_only_tickers(session, settings.BSE_CM_CSV_URL, nse_map)

                # Combine, format, and clean
                nse_tickers = [f"{symbol}.NS" for symbol in nse_map.values()]
                final_list = sorted(nse_tickers + bse_only_tickers)
            except Exception as e:
                logger.critical(f"Could not construct ticker universe from live sources: {e}")
                return []
        
        logger.info(f"Total Unique Tickers to Scan: {len(final_list)}")

        # Cache the final list for the day.
        with open(TickerLoader.CACHE_FILE, "w") as f:
            f.write("\n".join(final_list))
        logger.info(f"Saved {len(final_list)} tickers to cache: {TickerLoader.CACHE_FILE}")
            
        return final_list

class Bhavcopy:
    BHAVCOPY_CACHE_FILE = "bhavcopy_cache.csv"

    @staticmethod
    def get_bhavcopy_url_for_date(trade_date: datetime.date) -> str:
        """Constructs the Bhavcopy URL for a given date."""
        settings = get_settings()
        date_str = trade_date.strftime("%Y%m%d")
        return settings.BHAVCOPY_URL_TEMPLATE.format(date=date_str)

    @staticmethod
    def is_bhavcopy_available_for_date(trade_date: datetime.date, settings_obj=None) -> bool:
        """
        Checks if the Bhavcopy ZIP exists for a specific trading date.
        Uses HEAD first and falls back to GET if the server blocks HEAD.
        """
        settings = settings_obj or get_settings()
        if not getattr(settings, "BHAVCOPY_URL_TEMPLATE", None):
            logger.warning("BHAVCOPY_URL_TEMPLATE is not configured.")
            return False

        date_str = trade_date.strftime("%Y%m%d")
        url = settings.BHAVCOPY_URL_TEMPLATE.format(date=date_str)

        try:
            with requests.Session() as session:
                session.headers.update(TickerLoader.get_headers())
                head_resp = session.head(url, timeout=15, allow_redirects=True)
                if head_resp.status_code == 200:
                    return True
                if head_resp.status_code in (403, 405):
                    get_resp = session.get(url, timeout=15, stream=True, allow_redirects=True)
                    return get_resp.status_code == 200
                return False
        except Exception as e:
            logger.warning(f"Bhavcopy availability check failed for {trade_date}: {e}")
            return False

    @staticmethod
    def download_and_extract_bhavcopy(url: str, session: requests.Session) -> pd.DataFrame:
        """Downloads and extracts the Bhavcopy CSV."""
        logger.info(f"Fetching Bhavcopy from: {url}")
        response = session.get(url, timeout=30)
        response.raise_for_status()
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            # The CSV filename inside the zip is the same as the zip filename without the .zip extension
            csv_filename = z.namelist()[0]
            with z.open(csv_filename) as f:
                df = pd.read_csv(f)
                df.columns = [c.strip() for c in df.columns]
                return df

    @staticmethod
    def get_bhavcopy_data() -> pd.DataFrame:
        """
        Downloads, caches, and returns the Bhavcopy data for the current trading day.
        Handles market holidays by checking previous days.
        """
        if os.path.exists(Bhavcopy.BHAVCOPY_CACHE_FILE):
            if datetime.date.fromtimestamp(os.path.getmtime(Bhavcopy.BHAVCOPY_CACHE_FILE)) == datetime.date.today():
                logger.info(f"Loading Bhavcopy from today's cache: {Bhavcopy.BHAVCOPY_CACHE_FILE}")
                return pd.read_csv(Bhavcopy.BHAVCOPY_CACHE_FILE)

        logger.info("Bhavcopy cache not found for today. Fetching fresh data...")
        
        with requests.Session() as session:
            session.headers.update(TickerLoader.get_headers())
            
            # Iterate backwards from today to find the last trading day
            for i in range(7):
                trade_date = datetime.date.today() - datetime.timedelta(days=i)
                if trade_date.weekday() >= 5: # Skip weekends
                    continue
                
                try:
                    url = Bhavcopy.get_bhavcopy_url_for_date(trade_date)
                    df = Bhavcopy.download_and_extract_bhavcopy(url, session)
                    
                    # Filter for equity series
                    equity_df = df[df['SctySrs'] == 'EQ'].copy()
                    equity_df.to_csv(Bhavcopy.BHAVCOPY_CACHE_FILE, index=False)
                    logger.info(f"Saved Bhavcopy for {trade_date} to cache.")
                    return equity_df
                
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Could not fetch Bhavcopy for {trade_date}: {e}. Trying previous day.")
                    continue
        
        logger.critical("Could not fetch Bhavcopy for the last 7 days. Aborting.")
        return pd.DataFrame()
