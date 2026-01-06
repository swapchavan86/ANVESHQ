import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from functools import lru_cache

# --- Precedence Order ---
# 1. Environment Variables (highest priority)
# 2. .env file (for local development)
# 3. Default values defined in the Settings class (lowest priority)

# Build absolute path for the project root, starting from this file's location.
# This ensures that file paths are resolved correctly, regardless of the script's entry point.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

class Settings(BaseSettings):
    """
    Centralized application configuration.
    Defines all configuration parameters and their sources.
    """
    
    # --- Execution Mode ---
    # Defines the runtime environment (e.g., DEV, PROD, TEST).
    # Defaults to "DEV" if not specified.
    MODE: str = "DEV"
    
    # --- Database URLs ---
    # The primary database connection string. This is a required field.
    DATABASE_URL: str
    # The test database connection string. Optional, as it's only needed for test runs.
    TEST_DATABASE_URL: Optional[str] = None
    
    # --- Universe Settings ---
    # If True, the stock universe is loaded from the master JSON file.
    # If False, it falls back to live NSE/BSE feeds.
    USE_JSON_UNIVERSE: bool = True
    # Defines the path to the master JSON file for the stock universe.
    JSON_UNIVERSE_PATH: str = os.path.join(_PROJECT_ROOT, "data", "master", "master-latest.json")

    # --- Logging ---
    # Controls the logging verbosity. Defaults to "INFO".
    LOG_LEVEL: str = "INFO"

    # --- Application Metadata ---
    APP_NAME: str = "MomentumScanner"
    TIMEZONE: str = "Asia/Kolkata"
    
    # --- Universe Source URLs ---
    NSE_EQUITY_LIST_URL: str
    NSE_NIFTY500_CSV_URL: str
    BSE_CM_CSV_URL: str
    BHAVCOPY_URL_TEMPLATE: str

    # --- Core Logic Settings ---
    FUNDAMENTAL_CHECK_ENABLED: bool
    MIN_PRICE: float
    MIN_MCAP_CRORES: float
    STREAK_THRESHOLD_DAYS: int

    # --- Filtering Logic Settings ---
    NEAR_52_WEEK_HIGH_THRESHOLD: float
    VOLUME_CONFIRMATION_FACTOR: float
    RELATIVE_LIQUIDITY_FACTOR: float

    # --- Momentum Rank System Settings ---
    MAX_RANK: int
    DECAY_FACTOR: float
    
    model_config = SettingsConfigDict(
        # For local development, read settings from a .env file at the project root.
        env_file=os.path.join(_PROJECT_ROOT, 'Backend', '.env'), 
        env_file_encoding="utf-8", 
        extra='ignore'
    )

@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached instance of the Settings class.
    Using lru_cache ensures the settings are loaded only once.
    """
    return Settings()