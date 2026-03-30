from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.schemas import DelegateUserRequest, TokenResponse, UserResponse
from src.auth.schema import ensure_identity_schema
from src.auth.security import create_access_token, hash_password, verify_password
from src.models import SubscriptionTier, User, UserRole


class AuthService:
    TIER_ORDER = {
        SubscriptionTier.FREE: 0,
        SubscriptionTier.PRO: 1,
        SubscriptionTier.ELITE: 2,
    }

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def ensure_schema() -> None:
        ensure_identity_schema()

    @staticmethod
    def get_user_by_email(session: Session, email: str) -> User | None:
        normalized_email = AuthService.normalize_email(email)
        stmt = select(User).where(User.email == normalized_email)
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_user_by_id(session: Session, user_id: int) -> User | None:
        stmt = select(User).where(User.id == user_id)
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def _ensure_unique_email(session: Session, email: str) -> None:
        if AuthService.get_user_by_email(session, email):
            raise ValueError("A user with this email already exists.")

    @staticmethod
    def register_user(
        session: Session,
        email: str,
        password: str,
        role: UserRole = UserRole.USER,
        current_tier: SubscriptionTier = SubscriptionTier.FREE,
        delegated_by: User | None = None,
        telegram_chat_id: str | None = None,
    ) -> User:
        AuthService.ensure_schema()
        normalized_email = AuthService.normalize_email(email)
        AuthService._ensure_unique_email(session, normalized_email)

        user = User(
            email=normalized_email,
            hashed_password=hash_password(password),
            role=role,
            current_tier=current_tier,
            delegated_by=delegated_by,
            telegram_chat_id=telegram_chat_id,
        )
        session.add(user)
        session.flush()
        return user

    @staticmethod
    def authenticate_user(session: Session, email: str, password: str) -> User | None:
        user = AuthService.get_user_by_email(session, email)
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return AuthService.sync_subscription_state(session, user)

    @staticmethod
    def effective_tier(user: User) -> SubscriptionTier:
        if user.subscription_expiry is None:
            return user.current_tier

        expiry = user.subscription_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry < datetime.now(timezone.utc):
            return SubscriptionTier.FREE
        return user.current_tier

    @staticmethod
    def sync_subscription_state(session: Session, user: User) -> User:
        effective_tier = AuthService.effective_tier(user)
        if effective_tier != user.current_tier:
            user.current_tier = effective_tier
            if effective_tier == SubscriptionTier.FREE:
                user.subscription_expiry = None
            session.flush()
        return user

    @staticmethod
    def issue_token(user: User) -> TokenResponse:
        token, expires_at = create_access_token(
            subject=str(user.id),
            role=user.role.value,
            tier=AuthService.effective_tier(user).value,
        )
        return TokenResponse(
            access_token=token,
            expires_at=expires_at,
            user=UserResponse.model_validate(user),
        )

    @staticmethod
    def list_users(session: Session) -> list[User]:
        stmt = select(User).order_by(User.created_at.desc(), User.id.desc())
        return session.execute(stmt).scalars().all()

    @staticmethod
    def delegate_user(session: Session, acting_user: User, request: DelegateUserRequest) -> User:
        if acting_user.role not in {UserRole.SUPER_ADMIN, UserRole.ADMIN}:
            raise PermissionError("Only admins can delegate user access.")

        delegated_user = AuthService.register_user(
            session=session,
            email=request.email,
            password=request.password,
            role=request.role,
            current_tier=request.current_tier,
            delegated_by=acting_user,
            telegram_chat_id=request.telegram_chat_id,
        )
        return delegated_user

    @staticmethod
    def update_telegram_chat_id(session: Session, user: User, telegram_chat_id: str | None) -> User:
        user.telegram_chat_id = telegram_chat_id
        session.flush()
        return user
