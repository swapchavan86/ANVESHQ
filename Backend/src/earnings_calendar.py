import datetime
import json
import os
from pathlib import Path

import pandas as pd
import requests

from src.yahoo_finance import get_ticker


CACHE_FILE = Path(__file__).resolve().parents[1] / "earnings_cache.json"
CACHE_TTL_DAYS = 7


class EarningsCalendar:
    @staticmethod
    def _load_cache() -> dict:
        if not CACHE_FILE.exists():
            return {}
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _save_cache(cache: dict) -> None:
        os.makedirs(CACHE_FILE.parent, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    @staticmethod
    def _coerce_date(value) -> datetime.date | None:
        if value is None:
            return None
        if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
            return value
        if isinstance(value, (list, tuple)) and value:
            return EarningsCalendar._coerce_date(value[0])
        try:
            timestamp = pd.Timestamp(value)
            if pd.isna(timestamp):
                return None
            return timestamp.date()
        except Exception:
            return None

    @staticmethod
    def _get_yfinance_earnings_date(symbol: str) -> datetime.date | None:
        ticker = get_ticker(symbol)
        calendar = getattr(ticker, "calendar", None)
        if callable(calendar):
            calendar = calendar()
        if calendar is None:
            return None
        if isinstance(calendar, pd.DataFrame):
            if "Earnings Date" in calendar.index:
                return EarningsCalendar._coerce_date(calendar.loc["Earnings Date"].dropna().iloc[0])
            if "Earnings Date" in calendar.columns:
                return EarningsCalendar._coerce_date(calendar["Earnings Date"].dropna().iloc[0])
        if isinstance(calendar, dict):
            return EarningsCalendar._coerce_date(calendar.get("Earnings Date") or calendar.get("earningsDate"))
        return None

    @staticmethod
    def _get_nse_earnings_date(symbol: str) -> datetime.date | None:
        if not symbol.endswith(".NS"):
            return None
        base_symbol = symbol.replace(".NS", "")
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.nseindia.com/",
        }
        try:
            session = requests.Session()
            session.get("https://www.nseindia.com", headers=headers, timeout=10)
            response = session.get(
                "https://www.nseindia.com/api/event-calendar?index=equities",
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            events = payload if isinstance(payload, list) else payload.get("data", [])
            future_dates = []
            today = datetime.date.today()
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_symbol = event.get("symbol") or event.get("companySymbol")
                if event_symbol != base_symbol:
                    continue
                event_date = EarningsCalendar._coerce_date(
                    event.get("exDate") or event.get("date") or event.get("eventDate")
                )
                if event_date and event_date >= today:
                    future_dates.append(event_date)
            return min(future_dates) if future_dates else None
        except Exception:
            return None

    @staticmethod
    def get_next_earnings_date(symbol: str) -> datetime.date | None:
        cache = EarningsCalendar._load_cache()
        cached = cache.get(symbol)
        if isinstance(cached, dict):
            try:
                fetched_date = datetime.date.fromisoformat(cached.get("fetched_date", ""))
                if (datetime.date.today() - fetched_date).days < CACHE_TTL_DAYS:
                    earnings_date = cached.get("earnings_date")
                    return datetime.date.fromisoformat(earnings_date) if earnings_date else None
            except Exception:
                pass

        earnings_date = None
        for loader in (EarningsCalendar._get_yfinance_earnings_date, EarningsCalendar._get_nse_earnings_date):
            try:
                earnings_date = loader(symbol)
            except Exception:
                earnings_date = None
            if earnings_date:
                break

        cache[symbol] = {
            "earnings_date": earnings_date.isoformat() if earnings_date else None,
            "fetched_date": datetime.date.today().isoformat(),
        }
        EarningsCalendar._save_cache(cache)
        return earnings_date

    @staticmethod
    def is_near_earnings(symbol: str, today: datetime.date, settings_obj) -> tuple[bool, str | None]:
        earnings_date = EarningsCalendar.get_next_earnings_date(symbol)
        if earnings_date is None:
            return False, None

        days_to_earnings = (earnings_date - today).days
        days_since_earnings = (today - earnings_date).days
        if 0 <= days_to_earnings <= settings_obj.EARNINGS_BUFFER_DAYS_BEFORE:
            return True, f"Earnings in {days_to_earnings} days on {earnings_date}"
        if 0 <= days_since_earnings <= settings_obj.EARNINGS_BUFFER_DAYS_AFTER:
            return True, f"Recent earnings {days_since_earnings} days ago on {earnings_date}"
        return False, None
