import yfinance as yf
from requests import Session
from requests_cache import CacheMixin, SQLiteCache
from requests_ratelimiter import LimiterMixin, MemoryQueueBucket
from pyrate_limiter import Duration, RequestRate, Limiter

class YFinanceSession(CacheMixin, LimiterMixin, Session):
    pass

session = YFinanceSession(
    limiter=Limiter(RequestRate(2, Duration.SECOND * 5)),  # max 2 requests per 5 seconds
    bucket_class=MemoryQueueBucket,
    backend=SQLiteCache("yfinance.cache"),
)

def get_ticker(symbol: str) -> yf.Ticker:
    """
    Returns a yfinance Ticker object with a cached and rate-limited session.
    """
    ticker = yf.Ticker(symbol, session=session)
    return ticker