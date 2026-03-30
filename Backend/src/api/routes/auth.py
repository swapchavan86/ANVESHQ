from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user, get_db_session
from src.auth.schemas import LoginRequest, RegisterRequest, TelegramUpdateRequest, TokenResponse, UserResponse
from src.auth.service import AuthService
from src.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, session: Session = Depends(get_db_session)):
    try:
        user = AuthService.register_user(
            session,
            email=payload.email,
            password=payload.password,
            telegram_chat_id=payload.telegram_chat_id,
        )
        return AuthService.issue_token(user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_db_session)):
    user = AuthService.authenticate_user(session, payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    return AuthService.issue_token(user)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.patch("/me/telegram", response_model=UserResponse)
def update_telegram(
    payload: TelegramUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    session.add(current_user)
    user = AuthService.update_telegram_chat_id(session, current_user, payload.telegram_chat_id)
    return UserResponse.model_validate(user)
