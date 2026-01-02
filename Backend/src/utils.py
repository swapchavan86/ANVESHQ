import pandas as pd
import requests
import io
import logging
from src.config import get_settings
from src.database import get_db_context
from src.services import ErrorLogger

logger = logging.getLogger("TickerLoader")

class TickerLoader:
    
    @staticmethod
    def get_headers():
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

    @staticmethod
    def get_unique_tickers() -> list[str]:
        """
        Fetches NSE 500 and BSE All. 
        Merges them, ensuring NO duplicates using ISIN as the unique key.
        Prioritizes NSE listing over BSE.
        """
        settings = get_settings() # Get settings here
        
        # --- STEP 1: LOAD NSE (Priority) ---
        nse_map = {} # Stores {ISIN: Ticker}
        try:
            logger.info(f"Fetching NSE list from: {settings.NSE_STOCKS_URL}")
            r_nse = requests.get(settings.NSE_STOCKS_URL, headers=TickerLoader.get_headers(), timeout=15)
            r_nse.raise_for_status()
            
            df_nse = pd.read_csv(io.StringIO(r_nse.content.decode('utf-8')))
            
            # Normalize headers
            df_nse.columns = [c.strip() for c in df_nse.columns]
            
            for _, row in df_nse.iterrows():
                isin = row.get('ISIN Code')
                symbol = row.get('Symbol')
                
                if isin and symbol:
                    # NSE Ticker Format for Yahoo Finance
                    ticker = f"{symbol}.NS"
                    nse_map[isin] = ticker
            
            logger.info(f"Loaded {len(nse_map)} unique NSE stocks.")
            
        except Exception as e:
            logger.critical(f"NSE Fetch Failed: {e}")
            with get_db_context() as session:
                ErrorLogger.log_error(session, str(e))
            return []

        # --- STEP 2: LOAD BSE & DEDUPLICATE ---
        bse_tickers = []
        try:
            logger.info(f"Fetching BSE list from: {settings.BSE_STOCKS_URL}")
            r_bse = requests.get(settings.BSE_STOCKS_URL, timeout=30)
            r_bse.raise_for_status()
            
            # Fyers BSE_CM.csv has NO HEADERS.
            # We read it without header
            df_bse = pd.read_csv(io.StringIO(r_bse.content.decode('utf-8')), header=None)
            
            count_bse_only = 0
            
            for _, row in df_bse.iterrows():
                isin = None
                scrip_code = None
                
                # Dynamic scan for ISIN (Starts with INE/INF)
                for col_val in row.values:
                    val_str = str(col_val)
                    if val_str.startswith("INE") or val_str.startswith("INF"):
                        isin = val_str
                        break
                
                if not isin: 
                    continue
                    
                # --- DEDUPLICATION CHECK ---
                # If ISIN exists in NSE map, we skip this BSE record entirely.
                if isin in nse_map:
                    continue 
                
                # --- EXTRACT BSE CODE ---
                # If we are here, it's an exclusive BSE stock.
                for col_val in row.values:
                    val_str = str(col_val)
                    if val_str.isdigit() and len(val_str) == 6:
                        scrip_code = val_str
                        break

                if scrip_code:
                    ticker = f"{scrip_code}.BO"
                    bse_tickers.append(ticker)
                    count_bse_only += 1

            logger.info(f"Found {count_bse_only} stocks exclusive to BSE (Not in NSE list).")
            
        except Exception as e:
            logger.error(f"BSE Fetch Failed (Non-critical): {e}")
            with get_db_context() as session:
                ErrorLogger.log_error(session, str(e))

        # --- STEP 3: COMBINE ---
        final_list = list(nse_map.values()) + bse_tickers
        logger.info(f"Total Unique Tickers to Scan: {len(final_list)}")
        
        return final_list
