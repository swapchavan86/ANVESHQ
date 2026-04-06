import yfinance as yf
import pandas as pd
import logging

logger = logging.getLogger("Anveshq.YahooFinance")
yf_logger = logging.getLogger("yfinance")
yf_logger.setLevel(logging.CRITICAL)
yf_logger.propagate = False

def get_ticker(symbol: str) -> yf.Ticker:
    """
    Returns a yfinance Ticker object.

    yfinance 1.0 no longer supports request-cache sessions because it relies on
    curl_cffi internally, so we let yfinance manage its own HTTP layer.
    """
    ticker = yf.Ticker(symbol)
    return ticker


def is_unauthorized_error(exc: Exception) -> bool:
    text = str(exc)
    normalized = text.lower()
    return (
        "http error 401" in normalized
        or '"code":"unauthorized"' in normalized
        or "user is unable to access this feature" in normalized
        or "unauthorized" in normalized
    )


def is_rate_limited_error(exc: Exception) -> bool:
    text = str(exc)
    normalized = text.lower()
    return (
        "too many requests" in normalized
        or "rate limited" in normalized
        or "yfratelimiterror" in normalized
    )


def is_invalid_crumb_error(exc: Exception) -> bool:
    text = str(exc)
    normalized = text.lower()
    return "invalid crumb" in normalized or "crumb" in normalized


def is_recoverable_yahoo_error(exc: Exception) -> bool:
    return (
        is_unauthorized_error(exc)
        or is_rate_limited_error(exc)
        or is_invalid_crumb_error(exc)
    )


def download_history(symbol: str, **kwargs) -> pd.DataFrame:
    request_args = {"progress": False, "threads": False}
    request_args.update(kwargs)
    try:
        data = yf.download(symbol, **request_args)
        return data if data is not None else pd.DataFrame()
    except Exception as exc:
        if is_recoverable_yahoo_error(exc):
            logger.info("Yahoo Finance download unavailable for %s. Falling back without Yahoo history.", symbol)
            return pd.DataFrame()
        raise


def get_info(symbol: str, ticker: yf.Ticker | None = None) -> dict:
    active_ticker = ticker or get_ticker(symbol)
    try:
        if hasattr(active_ticker, "get_info"):
            info = active_ticker.get_info()
        else:
            info = active_ticker.info
        return info if isinstance(info, dict) else {}
    except Exception as exc:
        if is_recoverable_yahoo_error(exc):
            logger.info("Yahoo Finance info unavailable for %s. Continuing with fallback metadata sources.", symbol)
            return {}
        raise


def get_fast_info(symbol: str, ticker: yf.Ticker | None = None) -> dict:
    active_ticker = ticker or get_ticker(symbol)
    try:
        fast_info = getattr(active_ticker, "fast_info", None)
        if fast_info is None:
            return {}
        if isinstance(fast_info, dict):
            return fast_info
        items = getattr(fast_info, "items", None)
        if callable(items):
            return dict(items())
        return dict(fast_info)
    except Exception as exc:
        if is_recoverable_yahoo_error(exc):
            logger.info("Yahoo Finance fast_info unavailable for %s. Continuing without fast metadata.", symbol)
            return {}
        raise


def get_company_name(symbol: str) -> str | None:
    info = get_info(symbol)
    company_name = info.get("shortName") or info.get("longName")
    if isinstance(company_name, str):
        cleaned = company_name.strip()
        return cleaned or None
    return None
