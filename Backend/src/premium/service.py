from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

from src.auth.service import AuthService
from src.config import get_settings
from src.models import MomentumStock, SubscriptionTier, User
from src.premium.cache import InMemoryTTLCache
from src.services import StockFetcher

TOP_STOCKS_CACHE = InMemoryTTLCache()


class PremiumAnalyticsService:
    @staticmethod
    def _serialize_stock(stock: MomentumStock) -> dict:
        return {
            "symbol": stock.symbol,
            "company_name": stock.company_name,
            "rank_score": stock.rank_score,
            "daily_rank_delta": stock.daily_rank_delta,
            "current_price": stock.current_price,
            "last_seen_date": stock.last_seen_date.isoformat() if stock.last_seen_date else None,
            "risk_score": stock.risk_score,
        }

    @staticmethod
    def _top_limit_for_tier(tier: SubscriptionTier) -> int | None:
        if tier == SubscriptionTier.FREE:
            return 5
        if tier == SubscriptionTier.PRO:
            return 20
        return None

    @staticmethod
    def get_top_stocks(session: Session, user: User, force_refresh: bool = False) -> dict:
        settings = get_settings()
        effective_tier = AuthService.effective_tier(user)
        cache_key = f"top:{effective_tier.value}"
        cached_payload = None if force_refresh else TOP_STOCKS_CACHE.get(cache_key)
        if cached_payload is not None:
            return cached_payload

        current_date = datetime.now(ZoneInfo(settings.TIMEZONE)).date()
        stmt = (
            select(MomentumStock)
            .where(MomentumStock.is_active.is_(True))
            .order_by(desc(MomentumStock.rank_score), desc(MomentumStock.daily_rank_delta), asc(MomentumStock.symbol))
        )
        if effective_tier == SubscriptionTier.FREE:
            stmt = stmt.where(MomentumStock.last_seen_date <= current_date - timedelta(days=1))

        limit = PremiumAnalyticsService._top_limit_for_tier(effective_tier)
        if limit is not None:
            stmt = stmt.limit(limit)

        stocks = session.execute(stmt).scalars().all()
        payload = {
            "tier": effective_tier.value,
            "delay_hours": settings.DEFAULT_FREE_DELAY_HOURS if effective_tier == SubscriptionTier.FREE else 0,
            "items": [PremiumAnalyticsService._serialize_stock(stock) for stock in stocks],
        }
        TOP_STOCKS_CACHE.set(cache_key, payload, settings.API_CACHE_TTL_SECONDS)
        return payload

    @staticmethod
    async def _get_symbol_dataframe(symbol: str) -> pd.DataFrame:
        settings = get_settings()
        result = await StockFetcher.fetch_symbol_market_data_async(symbol, settings)
        if result.error:
            raise ValueError(result.error)
        return result.df

    @staticmethod
    def _compute_rsi(close_prices: pd.Series, period: int = 14) -> float | None:
        if len(close_prices) < period + 1:
            return None
        delta = close_prices.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None

    @staticmethod
    def _compute_macd(close_prices: pd.Series) -> tuple[float | None, float | None]:
        if len(close_prices) < 35:
            return None, None
        ema_12 = close_prices.ewm(span=12, adjust=False).mean()
        ema_26 = close_prices.ewm(span=26, adjust=False).mean()
        macd = ema_12 - ema_26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_value = macd.iloc[-1]
        signal_value = signal.iloc[-1]
        return (
            float(macd_value) if not pd.isna(macd_value) else None,
            float(signal_value) if not pd.isna(signal_value) else None,
        )

    @staticmethod
    async def get_technical_snapshot(symbol: str) -> dict:
        df = await PremiumAnalyticsService._get_symbol_dataframe(symbol)
        if df.empty:
            raise ValueError(f"No technical data found for {symbol}.")
        close_prices = df["Close"].dropna()
        macd_value, signal_value = PremiumAnalyticsService._compute_macd(close_prices)
        return {
            "symbol": symbol,
            "current_price": float(close_prices.iloc[-1]),
            "rsi_14": PremiumAnalyticsService._compute_rsi(close_prices),
            "macd": macd_value,
            "macd_signal": signal_value,
            "lookback_rows": int(len(df)),
        }

    @staticmethod
    async def run_backtest(symbol: str, lookback_days: int = 180, initial_capital: float = 100000.0) -> dict:
        df = await PremiumAnalyticsService._get_symbol_dataframe(symbol)
        df = df.tail(max(60, lookback_days)).copy()
        if len(df) < 30:
            raise ValueError("Not enough data to run the backtest.")

        df["sma_20"] = df["Close"].rolling(20).mean()
        cash = initial_capital
        shares = 0.0
        trades: list[dict] = []

        for index, row in df.iterrows():
            close_price = float(row["Close"])
            sma_20 = row["sma_20"]
            if pd.isna(sma_20):
                continue

            if shares == 0 and close_price > float(sma_20):
                shares = cash / close_price
                cash = 0.0
                trades.append({"date": index.date().isoformat(), "action": "BUY", "price": close_price})
            elif shares > 0 and close_price < float(sma_20):
                cash = shares * close_price
                shares = 0.0
                trades.append({"date": index.date().isoformat(), "action": "SELL", "price": close_price})

        final_value = cash if shares == 0 else shares * float(df["Close"].iloc[-1])
        return {
            "symbol": symbol,
            "initial_capital": initial_capital,
            "final_value": round(final_value, 2),
            "absolute_return": round(final_value - initial_capital, 2),
            "return_pct": round(((final_value / initial_capital) - 1) * 100, 2),
            "trades": trades,
        }

    @staticmethod
    async def portfolio_audit(symbols: list[str]) -> dict:
        audits = []
        for symbol in symbols:
            df = await PremiumAnalyticsService._get_symbol_dataframe(symbol)
            if df.empty:
                continue
            close_prices = df["Close"].dropna()
            returns = close_prices.pct_change().dropna()
            audits.append(
                {
                    "symbol": symbol,
                    "current_price": float(close_prices.iloc[-1]),
                    "volatility_30d": round(float(returns.tail(30).std() * (252 ** 0.5)), 4) if len(returns) >= 30 else None,
                    "return_90d_pct": round(float(((close_prices.iloc[-1] / close_prices.iloc[max(0, len(close_prices) - 90)]) - 1) * 100), 2)
                    if len(close_prices) >= 2
                    else None,
                }
            )
        return {"items": audits, "count": len(audits)}
