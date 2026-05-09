import datetime
import logging

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import MomentumStock
from src.yahoo_finance import download_history


logger = logging.getLogger("Anveshq")


class ExitManager:
    @staticmethod
    def _current_close(symbol: str) -> float | None:
        try:
            df = download_history(symbol, period="5d", interval="1d", auto_adjust=True, timeout=10)
            if df is None or df.empty or "Close" not in df.columns:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            close = pd.to_numeric(df["Close"], errors="coerce").dropna()
            return float(close.iloc[-1]) if not close.empty else None
        except Exception as exc:
            logger.warning("EXIT: current close lookup failed for %s: %s", symbol, exc)
            return None

    @staticmethod
    def _close_position(stock: MomentumStock, today: datetime.date, price: float, reason: str) -> dict:
        stock.exit_date = today
        stock.exit_price = price
        stock.exit_reason = reason
        stock.realized_return_pct = ((price - stock.entry_price) / stock.entry_price) * 100 if stock.entry_price else None
        stock.is_active = False
        return {
            "symbol": stock.symbol,
            "entry_price": stock.entry_price,
            "exit_price": price,
            "realized_return_pct": stock.realized_return_pct,
            "exit_reason": reason,
            "holding_days": (today - stock.entry_date).days if stock.entry_date else None,
        }

    @staticmethod
    def update_trailing_stops(session: Session, settings_obj, today: datetime.date) -> list[dict]:
        stmt = select(MomentumStock).where(
            MomentumStock.entry_date.is_not(None),
            MomentumStock.exit_date.is_(None),
            MomentumStock.entry_price.is_not(None),
        )
        open_positions = session.execute(stmt).scalars().all()
        exited: list[dict] = []

        for stock in open_positions:
            current_price = stock.current_price or ExitManager._current_close(stock.symbol)
            if current_price is None:
                continue

            stock.high_water_mark = max(stock.high_water_mark or stock.entry_price or current_price, current_price)
            stock.trailing_stop_price = stock.high_water_mark * (1 - settings_obj.TRAILING_STOP_PCT / 100)
            hard_stop = (stock.entry_price or current_price) * (1 - settings_obj.HARD_STOP_LOSS_PCT / 100)
            holding_days = (today - stock.entry_date).days if stock.entry_date else 0

            if holding_days < settings_obj.MIN_HOLDING_DAYS:
                continue
            if current_price <= hard_stop:
                exited.append(ExitManager._close_position(stock, today, current_price, "HARD_STOP"))
            elif current_price <= stock.trailing_stop_price:
                exited.append(ExitManager._close_position(stock, today, current_price, "TRAILING_STOP"))
            elif holding_days >= settings_obj.MAX_HOLDING_DAYS:
                exited.append(ExitManager._close_position(stock, today, current_price, "TIME_EXIT"))

        return exited
