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
    NSE_STOCKS_URL: str
    BSE_STOCKS_URL: str
    FUNDAMENTAL_CHECK_ENABLED: bool = False
    
    STREAK_THRESHOLD_DAYS: int = 10
    MIN_PRICE: float = 20.0
    
    # --- Momentum Rank System ---
    MAX_RANK: int = 10
    DECAY_FACTOR: float = 0.8
    
    # --- UPDATED FOR GROWTH STOCKS ---
    # 250 Cr -> 100 Cr (To catch  micro/Small/Micro Cap Growth Stocks)
    MIN_MCAP_CRORES: float = 250.0 

    LOG_LEVEL: str = "INFO"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra='ignore')

@lru_cache
def get_settings() -> Settings:
    return Settings()