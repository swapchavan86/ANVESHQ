from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user, get_db_session
from src.models import PaymentProvider, SubscriptionTier, User
from src.payments.service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


class CheckoutRequest(BaseModel):
    provider: PaymentProvider
    tier: SubscriptionTier


@router.post("/checkout")
async def create_checkout(
    payload: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    try:
        return await PaymentService.create_checkout_session(session, current_user, payload.tier, payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/webhook/{provider}")
async def payment_webhook(provider: PaymentProvider, request: Request, session: Session = Depends(get_db_session)):
    payload = await request.body()
    signature_header = request.headers.get("Stripe-Signature") or request.headers.get("X-Razorpay-Signature")
    try:
        return PaymentService.handle_webhook(session, provider, payload, signature_header)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
