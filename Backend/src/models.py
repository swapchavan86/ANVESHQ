from datetime import date, datetime
from typing import List, Optional
import enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    USER = "user"


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ELITE = "elite"


class PaymentProvider(str, enum.Enum):
    STRIPE = "stripe"
    RAZORPAY = "razorpay"


class MomentumStock(Base):
    __tablename__ = "momentum_ranks"
    __table_args__ = (
        CheckConstraint("rank_score >= 0 AND rank_score <= 100", name="ck_rank_score_range"),
        CheckConstraint("daily_rank_delta >= -100 AND daily_rank_delta <= 100", name="ck_daily_rank_delta_range"),
        CheckConstraint("current_price IS NULL OR (current_price >= 1 AND current_price <= 100000)", name="ck_price_range"),
        Index("ix_momentum_symbol_last_seen", "symbol", "last_seen_date"),
        Index("ix_momentum_last_seen_date", "last_seen_date"),
        Index("ix_momentum_rank_score", "rank_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    rank_score: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_seen_date: Mapped[date] = mapped_column(Date, nullable=False)

    daily_rank_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_rank_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    last_top10_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    top10_hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_volume_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_fundamental_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    current_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_52_week: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_52_week_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    high_52_week_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_52_week_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Company health/validation controls.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    manual_delete_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_validated_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    validation_failed_since: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, onupdate=func.now(), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_role", "role"),
        Index("ix_users_current_tier", "current_tier"),
        Index("ix_users_subscription_expiry", "subscription_expiry"),
        Index("ix_users_delegated_by_id", "delegated_by_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, values_callable=lambda members: [member.value for member in members]),
        default=UserRole.USER,
        nullable=False,
    )
    current_tier: Mapped[SubscriptionTier] = mapped_column(
        Enum(SubscriptionTier, native_enum=False, values_callable=lambda members: [member.value for member in members]),
        default=SubscriptionTier.FREE,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    delegated_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True, index=True)
    subscription_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)

    delegated_by: Mapped[Optional["User"]] = relationship(
        "User",
        remote_side=[id],
        back_populates="delegated_users",
    )
    delegated_users: Mapped[List["User"]] = relationship(
        "User",
        back_populates="delegated_by",
        cascade="save-update",
    )
    subscription_events: Mapped[List["SubscriptionEvent"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, onupdate=func.now(), server_default=func.now())

    verifications: Mapped[List["VerificationCode"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    code: Mapped[str] = mapped_column(String(10))
    type: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="verifications")


class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"
    __table_args__ = (
        Index("ix_subscription_events_user_id", "user_id"),
        Index("ix_subscription_events_provider", "provider"),
        Index("ix_subscription_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider, native_enum=False, values_callable=lambda members: [member.value for member in members]),
        nullable=False,
    )
    external_customer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    external_subscription_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    external_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    tier: Mapped[SubscriptionTier] = mapped_column(
        Enum(SubscriptionTier, native_enum=False, values_callable=lambda members: [member.value for member in members]),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="subscription_events")


class Error(Base):
    __tablename__ = "errors"
    __table_args__ = (Index("ix_errors_timestamp", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    error_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    error_message: Mapped[str] = mapped_column(String(500))
    error_details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AppMetadata(Base):
    __tablename__ = "app_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
