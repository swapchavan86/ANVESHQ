from __future__ import annotations

import asyncio
import logging
import threading

import httpx
from sqlalchemy import select

from src.auth.service import AuthService
from src.database import get_db_context
from src.models import MomentumStock, SubscriptionTier, User

logger = logging.getLogger("Anveshq.Notifications")


class NotificationManager:
    @staticmethod
    def schedule_tiered_alerts(symbols: set[str], settings_obj) -> None:
        if not symbols:
            return
        if not settings_obj.TELEGRAM_BOT_TOKEN:
            logger.info("Telegram bot token not configured. Skipping live alerts for %s symbols.", len(symbols))
            return

        worker = threading.Thread(
            target=NotificationManager._dispatch_sync,
            args=(sorted(symbols), settings_obj),
            daemon=True,
        )
        worker.start()

    @staticmethod
    def _dispatch_sync(symbols: list[str], settings_obj) -> None:
        try:
            asyncio.run(NotificationManager._dispatch_async(symbols, settings_obj))
        except Exception as exc:
            logger.error("Failed to dispatch async Telegram alerts: %s", exc, exc_info=True)

    @staticmethod
    def _build_message(user: User, stocks: list[MomentumStock]) -> str:
        lines = [
            f"Anveshq {AuthService.effective_tier(user).value.upper()} alert",
            f"Qualified stocks: {len(stocks)}",
        ]
        stock_limit = 20 if AuthService.effective_tier(user) == SubscriptionTier.PRO else len(stocks)
        for stock in stocks[:stock_limit]:
            lines.append(
                f"{stock.symbol}: rank {stock.rank_score}, delta {stock.daily_rank_delta}, price {stock.current_price or 0:.2f}"
            )
        return "\n".join(lines)

    @staticmethod
    async def _dispatch_async(symbols: list[str], settings_obj) -> None:
        with get_db_context() as session:
            users = session.execute(
                select(User).where(
                    User.is_active.is_(True),
                    User.telegram_chat_id.is_not(None),
                    User.current_tier.in_([SubscriptionTier.PRO, SubscriptionTier.ELITE]),
                )
            ).scalars().all()
            if not users:
                return

            stocks = session.execute(
                select(MomentumStock).where(MomentumStock.symbol.in_(symbols)).order_by(MomentumStock.rank_score.desc())
            ).scalars().all()

        if not stocks:
            return

        async with httpx.AsyncClient(timeout=settings_obj.HTTPX_TIMEOUT_SECONDS) as client:
            tasks = []
            for user in users:
                effective_tier = AuthService.effective_tier(user)
                if effective_tier not in {SubscriptionTier.PRO, SubscriptionTier.ELITE}:
                    continue
                tasks.append(
                    NotificationManager._send_telegram_message(
                        client,
                        settings_obj.TELEGRAM_BOT_TOKEN,
                        user.telegram_chat_id,
                        NotificationManager._build_message(user, stocks),
                    )
                )
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    async def _send_telegram_message(client: httpx.AsyncClient, bot_token: str, chat_id: str | None, text: str) -> None:
        if not chat_id:
            return
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        response = await client.post(url, json={"chat_id": chat_id, "text": text})
        response.raise_for_status()
