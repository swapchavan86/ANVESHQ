import datetime as dt
import hmac
import hashlib
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.auth.service import AuthService
from src.auth.schemas import DelegateUserRequest
from src.config import get_settings
from src.database import get_db_context, get_engine, reset_db_components
from src.models import Base, MomentumStock, PaymentProvider, SubscriptionTier, User, UserRole
from src.payments.service import PaymentService
from src.premium.service import PremiumAnalyticsService, TOP_STOCKS_CACHE


@pytest.fixture
def configured_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_anveshq.db"
    master_dir = tmp_path / "master"
    master_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("MODE", "TEST")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("TEST_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DB_PASSWORD", "")
    monkeypatch.setenv("MASTER_DATA_DIRECTORY", str(master_dir))
    monkeypatch.setenv("JSON_UNIVERSE_PATH", str(master_dir / "master-latest.json"))
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "stripe-secret")

    get_settings.cache_clear()
    reset_db_components()
    Base.metadata.create_all(bind=get_engine())
    yield
    reset_db_components()
    get_settings.cache_clear()


def test_auth_service_registers_and_authenticates_user(configured_environment):
    with get_db_context() as session:
        user = AuthService.register_user(session, "pro@example.com", "strong-pass-1", current_tier=SubscriptionTier.PRO)
        issued_token = AuthService.issue_token(user)

    with get_db_context() as session:
        authenticated_user = AuthService.authenticate_user(session, "pro@example.com", "strong-pass-1")
        authenticated_tier = authenticated_user.current_tier if authenticated_user else None

    assert issued_token.user.email == "pro@example.com"
    assert authenticated_user is not None
    assert authenticated_tier == SubscriptionTier.PRO


def test_admin_can_delegate_user(configured_environment):
    with get_db_context() as session:
        admin = AuthService.register_user(session, "admin@example.com", "strong-pass-1", role=UserRole.ADMIN)
        admin_id = admin.id

    with get_db_context() as session:
        acting_admin = AuthService.get_user_by_email(session, "admin@example.com")
        delegated = AuthService.delegate_user(
            session,
            acting_admin,
            DelegateUserRequest(email="delegate@example.com", password="strong-pass-2", current_tier=SubscriptionTier.ELITE),
        )

    with get_db_context() as session:
        stored_user = AuthService.get_user_by_email(session, "delegate@example.com")
        delegated_by_id = stored_user.delegated_by_id if stored_user else None
        delegated_tier = stored_user.current_tier if stored_user else None

    assert stored_user is not None
    assert delegated_by_id == admin_id
    assert delegated_tier == SubscriptionTier.ELITE


def test_premium_top_stocks_respects_free_delay_and_limit(configured_environment):
    TOP_STOCKS_CACHE.invalidate_prefix("top:")
    today = dt.date.today()
    with get_db_context() as session:
        free_user = AuthService.register_user(session, "free@example.com", "strong-pass-1")
        for idx in range(8):
            session.add(
                MomentumStock(
                    symbol=f"OLD{idx}.NS",
                    last_seen_date=today - dt.timedelta(days=1),
                    rank_score=20 - idx,
                    daily_rank_delta=1,
                    current_price=100 + idx,
                    is_active=True,
                )
            )
        session.add(
            MomentumStock(
                symbol="TODAY.NS",
                last_seen_date=today,
                rank_score=99,
                daily_rank_delta=5,
                current_price=250.0,
                is_active=True,
            )
        )

    with get_db_context() as session:
        free_user = AuthService.get_user_by_email(session, "free@example.com")
        payload = PremiumAnalyticsService.get_top_stocks(session, free_user, force_refresh=True)

    assert payload["tier"] == SubscriptionTier.FREE.value
    assert len(payload["items"]) == 5
    assert all(item["symbol"] != "TODAY.NS" for item in payload["items"])


def test_stripe_webhook_upgrades_user_tier(configured_environment):
    with get_db_context() as session:
        user = AuthService.register_user(session, "stripe@example.com", "strong-pass-1")
        user_id = user.id

    payload_dict = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "customer": "cus_123",
                "customer_email": "stripe@example.com",
                "metadata": {"user_id": str(user_id), "tier": "elite"},
            }
        },
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    timestamp = "1710000000"
    signature = hmac.new(b"stripe-secret", f"{timestamp}.{payload_bytes.decode('utf-8')}".encode("utf-8"), hashlib.sha256).hexdigest()
    signature_header = f"t={timestamp},v1={signature}"

    with get_db_context() as session:
        result = PaymentService.handle_webhook(session, PaymentProvider.STRIPE, payload_bytes, signature_header)

    with get_db_context() as session:
        stored_user = session.execute(select(User).where(User.email == "stripe@example.com")).scalar_one()
        stored_tier = stored_user.current_tier
        stripe_customer_id = stored_user.stripe_customer_id

    assert result["status"] == "active"
    assert stored_tier == SubscriptionTier.ELITE
    assert stripe_customer_id == "cus_123"
