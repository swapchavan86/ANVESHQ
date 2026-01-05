from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "MomentumScanner"
    TIMEZONE: str = "Asia/Kolkata"
    
    # --- LOAD FROM .ENV ---
    MODE: str
    DATABASE_URL: Optional[str] = None
    TEST_DATABASE_URL: str
    
    # --- Universe Source URLs ---
    NSE_EQUITY_MASTER_API_URL: str = "https://www.nseindia.com/api/equity-master"
    NSE_NIFTY500_CSV_URL: str = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    BSE_CM_CSV_URL: str = "https://public.fyers.in/sym_details/BSE_CM.csv"

    FUNDAMENTAL_CHECK_ENABLED: bool = False
    
    STREAK_THRESHOLD_DAYS: int = 10
    MIN_PRICE: float = 20.0
    
    # --- Momentum Rank System ---
    MAX_RANK: int = 10
    DECAY_FACTOR: float = 0.8
    
    # --- UPDATED FOR GROWTH STOCKS ---
    # 500 Cr -> 100 Cr (To catch Small/Micro Cap Growth Stocks)
    MIN_MCAP_CRORES: float = 500.0 

    LOG_LEVEL: str = "INFO"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra='ignore')

@lru_cache
def get_settings() -> Settings:
    return Settings()