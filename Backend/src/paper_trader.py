import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.backtest import compute_net_return
from src.models import MomentumStock, PaperTrade


class PaperTrader:
    @staticmethod
    def open_trade(session: Session, stock: MomentumStock, settings_obj) -> PaperTrade | None:
        existing = session.execute(
            select(PaperTrade).where(PaperTrade.symbol == stock.symbol, PaperTrade.status == "OPEN")
        ).scalar_one_or_none()
        if existing is not None:
            return None

        if not stock.position_shares or not stock.position_value or not stock.current_price or not stock.stop_loss_price:
            return None

        trade = PaperTrade(
            symbol=stock.symbol,
            signal_date=stock.entry_date or stock.last_seen_date,
            entry_price=stock.entry_price or stock.current_price,
            stop_loss_price=stock.stop_loss_price,
            take_profit_price=stock.take_profit_price,
            trailing_stop_pct=settings_obj.TRAILING_STOP_PCT,
            position_shares=stock.position_shares,
            position_value=stock.position_value,
            rank_score_at_entry=stock.rank_score,
            risk_score_at_entry=stock.risk_score,
            status="OPEN",
        )
        session.add(trade)
        return trade

    @staticmethod
    def update_open_trades(session: Session, settings_obj, today: datetime.date) -> list[PaperTrade]:
        open_trades = session.execute(select(PaperTrade).where(PaperTrade.status == "OPEN")).scalars().all()
        closed: list[PaperTrade] = []
        for trade in open_trades:
            stock = session.execute(select(MomentumStock).where(MomentumStock.symbol == trade.symbol)).scalar_one_or_none()
            if stock is None or stock.exit_date is None or stock.exit_price is None:
                continue
            trade.exit_date = stock.exit_date
            trade.exit_price = stock.exit_price
            trade.holding_days = (trade.exit_date - trade.signal_date).days
            trade.gross_return_pct = ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100
            trade.net_return_pct = compute_net_return(
                trade.gross_return_pct,
                trade.entry_price,
                trade.exit_price,
                trade.position_shares,
                trade.holding_days or 0,
                settings_obj,
            )
            reason = stock.exit_reason or "TIME_EXIT"
            trade.status = {
                "HARD_STOP": "CLOSED_STOP",
                "TRAILING_STOP": "CLOSED_TRAIL",
                "TIME_EXIT": "CLOSED_TIME",
            }.get(reason, "CLOSED_TARGET")
            closed.append(trade)
        return closed

    @staticmethod
    def get_performance_summary(session: Session) -> dict:
        trades = session.execute(select(PaperTrade)).scalars().all()
        closed = [trade for trade in trades if trade.status != "OPEN"]
        open_trades = [trade for trade in trades if trade.status == "OPEN"]
        returns = [trade.net_return_pct for trade in closed if trade.net_return_pct is not None]
        return {
            "open_positions": len(open_trades),
            "closed_positions": len(closed),
            "win_rate_pct": (sum(1 for value in returns if value > 0) / len(returns) * 100) if returns else None,
            "average_net_return_pct": (sum(returns) / len(returns)) if returns else None,
            "cumulative_net_return_pct": sum(returns) if returns else 0.0,
        }
