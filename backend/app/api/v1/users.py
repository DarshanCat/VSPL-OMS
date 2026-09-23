from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.auth import AdminUserCreate, TempPasswordResult, UserOut, SetActiveRequest
from app.services.user_admin_service import UserAdminService

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Admin-only user directory. Never returns hashed_password -- UserOut has no such
    field."""
    return UserAdminService.list_users(db, current_user=user)


@router.post("", response_model=TempPasswordResult)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Creates exactly one account and returns its generated temporary password ONCE.
    Never overwrites an existing account with this email."""
    return UserAdminService.create_user(db, payload, current_user=user)


@router.post("/{user_id}/reset-password", response_model=TempPasswordResult)
def reset_password(
    user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return UserAdminService.reset_password(db, user_id, current_user=user)


@router.patch("/{user_id}/status", response_model=UserOut)
def set_status(
    user_id: str,
    payload: SetActiveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return UserAdminService.set_active(db, user_id, payload.is_active, current_user=user)
