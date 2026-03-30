from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models import SubscriptionTier, UserRole


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: UserRole
    current_tier: SubscriptionTier
    is_active: bool
    delegated_by_id: int | None = None
    stripe_customer_id: str | None = None
    subscription_expiry: datetime | None = None
    telegram_chat_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    telegram_chat_id: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse


class DelegateUserRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: UserRole = UserRole.USER
    current_tier: SubscriptionTier = SubscriptionTier.PRO
    telegram_chat_id: str | None = None


class TelegramUpdateRequest(BaseModel):
    telegram_chat_id: str | None = None
