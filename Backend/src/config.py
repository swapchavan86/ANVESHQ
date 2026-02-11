import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Build absolute project root from Backend/src/config.py.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _resolve_project_path(path_value: str) -> str:
    """Resolve a path relative to project root unless already absolute."""
    if os.path.isabs(path_value):
        return path_value
    return os.path.abspath(os.path.join(_PROJECT_ROOT, path_value))


def _sqlite_url_from_path(path_value: str) -> str:
    resolved = _resolve_project_path(path_value)
    normalized = resolved.replace("\\", "/")
    return f"sqlite:///{normalized}"


class Settings(BaseSettings):
    """
    Centralized application configuration.
    Environment variables override values from `.env`, which override defaults.
    """

    MODE: str = "DEV"

    # SQLite path-based configuration.
    DATABASE_PATH: str = "data/anveshq.db"
    TEST_DATABASE_PATH: str = "data/test_anveshq.db"

    USE_JSON_UNIVERSE: bool = True
    JSON_UNIVERSE_PATH: str = os.path.join("data", "master", "master-latest.json")
    MASTER_DATA_DIRECTORY: str = os.path.join("data", "master")

    LOG_LEVEL: str = "INFO"
    APP_NAME: str = "Anveshq"
    TIMEZONE: str = "Asia/Kolkata"

    # Universe source URLs.
    NSE_EQUITY_LIST_URL: str = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    NSE_NIFTY500_CSV_URL: str = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    BSE_CM_CSV_URL: str = ""
    BHAVCOPY_URL_TEMPLATE: str = (
        "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
    )

    # Core scan settings.
    FUNDAMENTAL_CHECK_ENABLED: bool = True
    MIN_PRICE: float = 20.0
    MIN_MCAP_CRORES: float = 1000.0
    STREAK_THRESHOLD_DAYS: int = 3

    # Filtering and ranking settings.
    NEAR_52_WEEK_HIGH_THRESHOLD: float = 0.90
    VOLUME_CONFIRMATION_FACTOR: float = 1.25
    RELATIVE_LIQUIDITY_FACTOR: float = 0.6
    REPETITION_COOLDOWN_DAYS: int = 14
    BREAKOUT_LOOKBACK_DAYS: int = 20
    MAX_RANK: int = 100
    DECAY_FACTOR: float = 0.2

    # Retention and cleanup settings.
    DATA_RETENTION_WEEKS: int = 104
    CLEANUP_FREQUENCY_DAYS: int = 7
    MASTER_DATA_RETENTION_DAYS: int = 7
    ERROR_LOG_RETENTION_DAYS: int = 90
    STALE_SYMBOL_DAYS: int = 30
    CLEANUP_BATCH_SIZE: int = 1000

    # Monitoring and DB lock handling.
    DB_SIZE_WARNING_MB: float = 80.0
    DB_LOCK_RETRY_COUNT: int = 3
    DB_LOCK_RETRY_DELAY_SECONDS: float = 1.0

    # Email settings.
    SMTP_HOST: str | None = "smtp.gmail.com"
    SMTP_PORT: int | None = 587
    SMTP_USE_SSL: bool = False
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    TO_EMAIL: str | None = None

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("MODE", mode="before")
    @classmethod
    def normalize_mode(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            return value.strip().strip('"').strip("'").upper()
        return value

    @property
    def database_file_path(self) -> str:
        return _resolve_project_path(self.DATABASE_PATH)

    @property
    def test_database_file_path(self) -> str:
        return _resolve_project_path(self.TEST_DATABASE_PATH)

    @property
    def database_url(self) -> str:
        return _sqlite_url_from_path(self.DATABASE_PATH)

    @property
    def test_database_url(self) -> str:
        return _sqlite_url_from_path(self.TEST_DATABASE_PATH)

    @property
    def active_database_url(self) -> str:
        return self.test_database_url if self.MODE == "TEST" else self.database_url

    @property
    def active_database_file_path(self) -> str:
        return self.test_database_file_path if self.MODE == "TEST" else self.database_file_path

    @property
    def master_data_directory(self) -> str:
        return _resolve_project_path(self.MASTER_DATA_DIRECTORY)

    @property
    def json_universe_file_path(self) -> str:
        return _resolve_project_path(self.JSON_UNIVERSE_PATH)


@lru_cache
def get_settings() -> Settings:
    """Return cached app settings."""
    return Settings()
