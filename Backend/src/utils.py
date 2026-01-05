import pandas as pd
import requests
import io
import logging
import os
import datetime
from src.config import get_settings

logger = logging.getLogger("TickerLoader")

class TickerLoader:
    CACHE_FILE = "universe_cache.txt"
    
    @staticmethod
    def get_headers():
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }

    @staticmethod
    def _fetch_nse_master(session: requests.Session, url: str) -> dict[str, str]:
        """Fetches all tradable equity instruments from the NSE Equity Master API."""
        nse_map = {}
        try:
            logger.info("Initializing NSE session and fetching Equity Master...")
            session.get("https://www.nseindia.com", timeout=15) # For cookies
            response = session.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            for instrument in data.values():
                if isinstance(instrument, dict) and instrument.get('instrumentType') == 'EQUITY':
                    isin = instrument.get('isin')
                    symbol = instrument.get('symbol')
                    if isin and symbol:
                        nse_map[isin] = symbol
            logger.info(f"Loaded {len(nse_map)} symbols from NSE Equity Master.")
        except Exception as e:
            logger.error(f"NSE Equity Master Fetch Failed: {e}")
        return nse_map

    @staticmethod
    def _overlay_nifty500(session: requests.Session, url: str, nse_map: dict[str, str]):
        """Overlays Nifty 500 symbols on top of the master list."""
        try:
            logger.info(f"Fetching Nifty 500 overlay from: {url}")
            response = session.get(url, timeout=15)
            response.raise_for_status()
            
            df = pd.read_csv(io.StringIO(response.content.decode('utf-8')))
            df.columns = [c.strip() for c in df.columns]
            
            count = 0
            for _, row in df.iterrows():
                isin = row.get('ISIN Code')
                symbol = row.get('Symbol')
                if isin and symbol and isin not in nse_map:
                    nse_map[isin] = symbol
                    count += 1
            logger.info(f"Overlayed {count} new symbols from Nifty 500.")
        except Exception as e:
            logger.error(f"Nifty 500 Overlay Failed: {e}")

    @staticmethod
    def _fetch_bse_only_tickers(session: requests.Session, url: str, nse_map: dict[str, str]) -> list[str]:
        """Fetches BSE symbols and returns only those not already in the NSE map."""
        bse_tickers = []
        try:
            logger.info(f"Fetching BSE list for coverage expansion from: {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            df = pd.read_csv(io.StringIO(response.content.decode('utf-8')), header=None)
            
            for _, row in df.iterrows():
                isin, scrip_code = None, None
                
                # Find ISIN and 6-digit scrip code in the row
                for val in row.values:
                    val_str = str(val)
                    if val_str.startswith("INE") or val_str.startswith("INF"):
                        isin = val_str
                    elif val_str.isdigit() and len(val_str) == 6:
                        scrip_code = val_str
                
                # If we have an ISIN and it's a new stock, add the BSE ticker
                if isin and scrip_code and isin not in nse_map:
                    bse_tickers.append(f"{scrip_code}.BO")

            logger.info(f"Found {len(bse_tickers)} stocks exclusive to BSE.")
        except Exception as e:
            logger.error(f"BSE Fetch Failed (Non-critical): {e}")
        return bse_tickers

    @staticmethod
    def get_unique_tickers() -> list[str]:
        """
        Fetches stock symbols from NSE and BSE, deduplicates using ISIN,
        and caches the result for the day.
        """
        if os.path.exists(TickerLoader.CACHE_FILE):
            if datetime.date.fromtimestamp(os.path.getmtime(TickerLoader.CACHE_FILE)) == datetime.date.today():
                logger.info(f"Loading tickers from today's cache: {TickerLoader.CACHE_FILE}")
                with open(TickerLoader.CACHE_FILE, "r") as f:
                    return [line.strip() for line in f if line.strip()]

        logger.info("Cache outdated or not found. Fetching fresh stock universe...")
        settings = get_settings()
        
        with requests.Session() as session:
            session.headers.update(TickerLoader.get_headers())
            
            # 1. Primary Source: NSE Master
            nse_map = TickerLoader._fetch_nse_master(session, settings.NSE_EQUITY_MASTER_API_URL)
            
            # 2. Secondary Source: Nifty 500 Overlay
            TickerLoader._overlay_nifty500(session, settings.NSE_NIFTY500_CSV_URL, nse_map)
            
            # 3. Tertiary Source: BSE for expansion
            bse_only_tickers = TickerLoader._fetch_bse_only_tickers(session, settings.BSE_CM_CSV_URL, nse_map)

        if not nse_map:
            logger.critical("Primary NSE fetch failed. Aborting.")
            return []

        # Combine, format, and clean
        nse_tickers = [f"{symbol}.NS" for symbol in nse_map.values()]
        final_list = sorted(nse_tickers + bse_only_tickers)
        
        logger.info(f"Total Unique Tickers to Scan: {len(final_list)}")

        try:
            with open(TickerLoader.CACHE_FILE, "w") as f:
                f.write("\n".join(final_list))
            logger.info(f"Saved {len(final_list)} tickers to cache: {TickerLoader.CACHE_FILE}")
        except Exception as e:
            logger.error(f"Failed to write to cache file: {e}")
            
        return final_list
