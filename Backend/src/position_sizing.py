import datetime
import zoneinfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import MomentumStock


class PositionSizer:
    @staticmethod
    def calculate_position(
        capital: float,
        entry_price: float,
        stop_loss_price: float,
        settings_obj,
    ) -> dict | None:
        if capital <= 0 or entry_price <= 0:
            return None

        risk_per_share = entry_price - stop_loss_price
        if risk_per_share <= 0:
            return None

        risk_amount = capital * (settings_obj.RISK_PER_TRADE_PCT / 100)
        shares_by_risk = int(risk_amount / risk_per_share)
        max_shares_by_pct = int((capital * settings_obj.MAX_POSITION_SIZE_PCT / 100) / entry_price)
        min_shares_by_pct = int((capital * settings_obj.MIN_POSITION_SIZE_PCT / 100) / entry_price)

        shares = min(shares_by_risk, max_shares_by_pct)
        if shares <= 0:
            return None
        shares = max(shares, min_shares_by_pct)

        position_value = shares * entry_price
        position_pct = (position_value / capital) * 100
        risk_amount_actual = shares * risk_per_share
        risk_pct_actual = (risk_amount_actual / capital) * 100

        return {
            "shares": shares,
            "position_value": position_value,
            "position_pct": position_pct,
            "risk_amount_actual": risk_amount_actual,
            "risk_pct_actual": risk_pct_actual,
        }

    @staticmethod
    def get_portfolio_heat(session: Session, capital: float) -> float:
        if capital <= 0:
            return 0.0

        today = datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).date()
        cutoff = today - datetime.timedelta(days=30)
        total_deployed = session.execute(
            select(func.coalesce(func.sum(MomentumStock.position_value), 0.0)).where(
                MomentumStock.is_active.is_(True),
                MomentumStock.entry_date.is_not(None),
                MomentumStock.exit_date.is_(None),
                MomentumStock.last_seen_date >= cutoff,
            )
        ).scalar_one()
        return (float(total_deployed or 0.0) / capital) * 100

    @staticmethod
    def get_active_position_count(session: Session) -> int:
        return int(
            session.execute(
                select(func.count(MomentumStock.id)).where(
                    MomentumStock.is_active.is_(True),
                    MomentumStock.entry_date.is_not(None),
                    MomentumStock.exit_date.is_(None),
                )
            ).scalar_one()
        )

    @staticmethod
    def can_add_position(
        session: Session,
        capital: float,
        new_position_value: float,
        settings_obj,
    ) -> tuple[bool, str | None]:
        if capital <= 0:
            return False, "Portfolio capital must be positive"

        current_heat = PositionSizer.get_portfolio_heat(session, capital)
        new_heat = current_heat + (new_position_value / capital * 100)
        active_count = PositionSizer.get_active_position_count(session)

        if active_count >= settings_obj.MAX_CONCURRENT_POSITIONS:
            return False, "Max concurrent positions reached"
        if new_heat > settings_obj.MAX_PORTFOLIO_HEAT_PCT:
            return False, f"Portfolio heat {new_heat:.1f}% exceeds limit"
        return True, None
