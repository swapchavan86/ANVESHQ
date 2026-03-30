from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.auth.dependencies import check_role, get_db_session
from src.auth.schemas import DelegateUserRequest, UserResponse
from src.auth.service import AuthService
from src.models import User, UserRole

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserResponse])
def list_users(
    _: User = Depends(check_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    session: Session = Depends(get_db_session),
):
    users = AuthService.list_users(session)
    return [UserResponse.model_validate(user) for user in users]


@router.post("/delegate", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def delegate_access(
    payload: DelegateUserRequest,
    acting_user: User = Depends(check_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    session: Session = Depends(get_db_session),
):
    try:
        delegated_user = AuthService.delegate_user(session, acting_user, payload)
        return UserResponse.model_validate(delegated_user)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
