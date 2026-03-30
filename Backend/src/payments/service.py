from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.service import AuthService
from src.config import get_settings
from src.models import PaymentProvider, SubscriptionEvent, SubscriptionTier, User


class PaymentService:
    TIER_PRICING = {
        SubscriptionTier.PRO: {"name": "Anveshq Pro", "amount_minor": 49900, "currency": "inr"},
        SubscriptionTier.ELITE: {"name": "Anveshq Elite", "amount_minor": 149900, "currency": "inr"},
    }

    @staticmethod
    def _ensure_paid_tier(tier: SubscriptionTier) -> None:
        if tier == SubscriptionTier.FREE:
            raise ValueError("Free tier does not require a checkout session.")

    @staticmethod
    async def create_checkout_session(session: Session, user: User, tier: SubscriptionTier, provider: PaymentProvider) -> dict:
        PaymentService._ensure_paid_tier(tier)
        if provider == PaymentProvider.STRIPE:
            return await PaymentService._create_stripe_checkout(session, user, tier)
        return await PaymentService._create_razorpay_checkout(user, tier)

    @staticmethod
    async def _create_stripe_checkout(session: Session, user: User, tier: SubscriptionTier) -> dict:
        settings = get_settings()
        if not settings.STRIPE_API_KEY:
            raise ValueError("Stripe API key is not configured.")

        pricing = PaymentService.TIER_PRICING[tier]
        payload = {
            "mode": "payment",
            "success_url": settings.PAYMENT_SUCCESS_URL,
            "cancel_url": settings.PAYMENT_CANCEL_URL,
            "customer_email": user.email,
            "client_reference_id": str(user.id),
            "metadata[user_id]": str(user.id),
            "metadata[tier]": tier.value,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": pricing["currency"],
            "line_items[0][price_data][unit_amount]": str(pricing["amount_minor"]),
            "line_items[0][price_data][product_data][name]": pricing["name"],
        }

        async with httpx.AsyncClient(timeout=settings.HTTPX_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                data=payload,
                headers={"Authorization": f"Bearer {settings.STRIPE_API_KEY}"},
            )
            response.raise_for_status()
            body = response.json()

        if body.get("customer"):
            user.stripe_customer_id = body["customer"]
            session.flush()

        return {
            "provider": PaymentProvider.STRIPE.value,
            "checkout_url": body.get("url"),
            "session_id": body.get("id"),
            "tier": tier.value,
        }

    @staticmethod
    async def _create_razorpay_checkout(user: User, tier: SubscriptionTier) -> dict:
        settings = get_settings()
        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise ValueError("Razorpay credentials are not configured.")

        pricing = PaymentService.TIER_PRICING[tier]
        auth_token = base64.b64encode(
            f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode("utf-8")
        ).decode("utf-8")
        payload = {
            "amount": pricing["amount_minor"],
            "currency": pricing["currency"].upper(),
            "accept_partial": False,
            "description": pricing["name"],
            "customer": {"email": user.email},
            "notify": {"email": True},
            "reference_id": f"anveshq-user-{user.id}-{tier.value}",
            "callback_url": settings.PAYMENT_SUCCESS_URL,
            "callback_method": "get",
            "notes": {"user_id": str(user.id), "tier": tier.value},
        }

        async with httpx.AsyncClient(timeout=settings.HTTPX_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://api.razorpay.com/v1/payment_links",
                json=payload,
                headers={"Authorization": f"Basic {auth_token}"},
            )
            response.raise_for_status()
            body = response.json()

        return {
            "provider": PaymentProvider.RAZORPAY.value,
            "checkout_url": body.get("short_url") or body.get("url"),
            "session_id": body.get("id"),
            "tier": tier.value,
        }

    @staticmethod
    def validate_webhook_signature(provider: PaymentProvider, payload: bytes, signature_header: str | None) -> None:
        settings = get_settings()
        if not signature_header:
            raise ValueError("Missing webhook signature.")

        if provider == PaymentProvider.STRIPE:
            if not settings.STRIPE_WEBHOOK_SECRET:
                raise ValueError("Stripe webhook secret is not configured.")
            parts = dict(part.split("=", 1) for part in signature_header.split(",") if "=" in part)
            timestamp = parts.get("t")
            expected_signature = parts.get("v1")
            signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
            digest = hmac.new(
                settings.STRIPE_WEBHOOK_SECRET.encode("utf-8"),
                signed_payload,
                hashlib.sha256,
            ).hexdigest()
            if not expected_signature or not hmac.compare_digest(digest, expected_signature):
                raise ValueError("Invalid Stripe webhook signature.")
            return

        if not settings.RAZORPAY_WEBHOOK_SECRET:
            raise ValueError("Razorpay webhook secret is not configured.")
        digest = hmac.new(settings.RAZORPAY_WEBHOOK_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest, signature_header):
            raise ValueError("Invalid Razorpay webhook signature.")

    @staticmethod
    def _parse_tier(value: str | None) -> SubscriptionTier:
        if not value:
            return SubscriptionTier.FREE
        normalized = value.strip().lower()
        for tier in SubscriptionTier:
            if tier.value == normalized:
                return tier
        return SubscriptionTier.FREE

    @staticmethod
    def _resolve_user(session: Session, user_id: str | None = None, email: str | None = None, stripe_customer_id: str | None = None) -> User:
        user = None
        if user_id:
            user = AuthService.get_user_by_id(session, int(user_id))
        if user is None and stripe_customer_id:
            stmt = select(User).where(User.stripe_customer_id == stripe_customer_id)
            user = session.execute(stmt).scalar_one_or_none()
        if user is None and email:
            user = AuthService.get_user_by_email(session, email)
        if user is None:
            raise ValueError("Unable to resolve user for payment event.")
        return user

    @staticmethod
    def _record_event(
        session: Session,
        user: User,
        provider: PaymentProvider,
        tier: SubscriptionTier,
        event_type: str,
        status: str,
        payload: dict,
        external_customer_id: str | None = None,
        external_subscription_id: str | None = None,
        external_session_id: str | None = None,
    ) -> SubscriptionEvent:
        event = SubscriptionEvent(
            user=user,
            provider=provider,
            tier=tier,
            event_type=event_type,
            status=status,
            payload=payload,
            external_customer_id=external_customer_id,
            external_subscription_id=external_subscription_id,
            external_session_id=external_session_id,
        )
        session.add(event)
        session.flush()
        return event

    @staticmethod
    def _activate_subscription(session: Session, user: User, tier: SubscriptionTier, stripe_customer_id: str | None = None) -> User:
        user.current_tier = tier
        user.subscription_expiry = datetime.now(timezone.utc) + timedelta(days=30)
        if stripe_customer_id:
            user.stripe_customer_id = stripe_customer_id
        session.flush()
        return user

    @staticmethod
    def _cancel_subscription(session: Session, user: User) -> User:
        user.current_tier = SubscriptionTier.FREE
        user.subscription_expiry = None
        session.flush()
        return user

    @staticmethod
    def handle_webhook(session: Session, provider: PaymentProvider, payload: bytes, signature_header: str | None) -> dict:
        PaymentService.validate_webhook_signature(provider, payload, signature_header)
        body = json.loads(payload.decode("utf-8"))

        if provider == PaymentProvider.STRIPE:
            return PaymentService._handle_stripe_webhook(session, body)
        return PaymentService._handle_razorpay_webhook(session, body)

    @staticmethod
    def _handle_stripe_webhook(session: Session, body: dict) -> dict:
        event_type = body.get("type", "unknown")
        data_object = body.get("data", {}).get("object", {})
        metadata = data_object.get("metadata", {})
        user = PaymentService._resolve_user(
            session,
            user_id=metadata.get("user_id") or data_object.get("client_reference_id"),
            email=data_object.get("customer_email") or data_object.get("customer_details", {}).get("email"),
            stripe_customer_id=data_object.get("customer"),
        )
        tier = PaymentService._parse_tier(metadata.get("tier"))

        if event_type == "checkout.session.completed":
            PaymentService._activate_subscription(session, user, tier, stripe_customer_id=data_object.get("customer"))
            PaymentService._record_event(
                session,
                user,
                PaymentProvider.STRIPE,
                tier,
                event_type,
                "active",
                body,
                external_customer_id=data_object.get("customer"),
                external_session_id=data_object.get("id"),
            )
            return {"status": "active", "tier": tier.value, "user_id": user.id}

        if event_type in {"customer.subscription.deleted", "invoice.payment_failed"}:
            PaymentService._cancel_subscription(session, user)
            PaymentService._record_event(
                session,
                user,
                PaymentProvider.STRIPE,
                SubscriptionTier.FREE,
                event_type,
                "cancelled",
                body,
                external_customer_id=data_object.get("customer"),
                external_subscription_id=data_object.get("subscription"),
            )
            return {"status": "cancelled", "tier": SubscriptionTier.FREE.value, "user_id": user.id}

        PaymentService._record_event(
            session,
            user,
            PaymentProvider.STRIPE,
            tier,
            event_type,
            "ignored",
            body,
            external_customer_id=data_object.get("customer"),
            external_session_id=data_object.get("id"),
        )
        return {"status": "ignored", "tier": tier.value, "user_id": user.id}

    @staticmethod
    def _handle_razorpay_webhook(session: Session, body: dict) -> dict:
        event_type = body.get("event", "unknown")
        payload = body.get("payload", {})
        payment_link = payload.get("payment_link", {}).get("entity", {})
        notes = payment_link.get("notes", {})
        tier = PaymentService._parse_tier(notes.get("tier"))
        user = PaymentService._resolve_user(
            session,
            user_id=notes.get("user_id"),
            email=payment_link.get("customer", {}).get("email"),
        )

        if event_type in {"payment_link.paid", "subscription.charged"}:
            PaymentService._activate_subscription(session, user, tier)
            PaymentService._record_event(
                session,
                user,
                PaymentProvider.RAZORPAY,
                tier,
                event_type,
                "active",
                body,
                external_session_id=payment_link.get("id"),
            )
            return {"status": "active", "tier": tier.value, "user_id": user.id}

        if event_type in {"payment_link.cancelled", "subscription.cancelled", "payment.failed"}:
            PaymentService._cancel_subscription(session, user)
            PaymentService._record_event(
                session,
                user,
                PaymentProvider.RAZORPAY,
                SubscriptionTier.FREE,
                event_type,
                "cancelled",
                body,
                external_session_id=payment_link.get("id"),
            )
            return {"status": "cancelled", "tier": SubscriptionTier.FREE.value, "user_id": user.id}

        PaymentService._record_event(
            session,
            user,
            PaymentProvider.RAZORPAY,
            tier,
            event_type,
            "ignored",
            body,
            external_session_id=payment_link.get("id"),
        )
        return {"status": "ignored", "tier": tier.value, "user_id": user.id}
