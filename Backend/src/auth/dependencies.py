from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from src.auth.schema import ensure_identity_schema
from src.auth.security import decode_access_token
from src.auth.service import AuthService
from src.database import get_session_local
from src.models import SubscriptionTier, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_db_session():
    ensure_identity_schema()
    session_local = get_session_local()
    session: Session = session_local()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_db_session)) -> User:
    try:
        payload = decode_access_token(token)
        subject = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token.") from exc

    user = AuthService.get_user_by_id(session, subject)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive.")
    return AuthService.sync_subscription_state(session, user)


def check_role(*allowed_roles: UserRole) -> Callable[[User], User]:
    allowed_values = {role.value if isinstance(role, UserRole) else str(role) for role in allowed_roles}

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in allowed_values:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for this resource.")
        return current_user

    return dependency


def check_tier(required_tier: SubscriptionTier) -> Callable[[User], User]:
    required_rank = AuthService.TIER_ORDER[required_tier]

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        effective_tier = AuthService.effective_tier(current_user)
        if AuthService.TIER_ORDER[effective_tier] < required_rank:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Upgrade required for this resource.")
        return current_user

    return dependency
