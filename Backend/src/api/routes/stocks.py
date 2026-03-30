from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.auth.dependencies import check_tier, get_current_user, get_db_session
from src.models import SubscriptionTier, User
from src.premium.service import PremiumAnalyticsService

router = APIRouter(tags=["stocks", "premium"])


class BacktestRequest(BaseModel):
    symbol: str
    lookback_days: int = Field(default=180, ge=60, le=365)
    initial_capital: float = Field(default=100000.0, gt=0)


class PortfolioAuditRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=20)


@router.get("/stocks/top")
def get_top_stocks(
    force_refresh: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    return PremiumAnalyticsService.get_top_stocks(session, current_user, force_refresh=force_refresh)


@router.get("/premium/technicals/{symbol}")
async def get_technicals(
    symbol: str,
    _: User = Depends(check_tier(SubscriptionTier.PRO)),
):
    try:
        return await PremiumAnalyticsService.get_technical_snapshot(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/premium/backtest")
async def backtest(
    payload: BacktestRequest,
    _: User = Depends(check_tier(SubscriptionTier.ELITE)),
):
    try:
        return await PremiumAnalyticsService.run_backtest(
            symbol=payload.symbol,
            lookback_days=payload.lookback_days,
            initial_capital=payload.initial_capital,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/premium/portfolio-audit", status_code=status.HTTP_200_OK)
async def portfolio_audit(
    payload: PortfolioAuditRequest,
    _: User = Depends(check_tier(SubscriptionTier.ELITE)),
):
    return await PremiumAnalyticsService.portfolio_audit(payload.symbols)
