from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, validate_company_email
from app.core.rate_limit import limiter
from app.api.deps import require_roles, get_current_user
from app.models.user import User, UserRole
from app.schemas.auth import UserLogin, UserCreate, Token, UserOut, ChangePasswordRequest
from app.services.user_admin_service import UserAdminService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.get("/me", response_model=UserOut)
def get_my_identity(user: User = Depends(get_current_user)):
    """Return the identity of the currently authenticated user, resolved server-side
    from the bearer token -- never client-supplied -- so the frontend can display the
    real logged-in user instead of a hardcoded placeholder."""
    return user

@router.post("/register", response_model=UserOut)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    normalized_email = validate_company_email(payload.email)
    if db.query(User).filter(User.email == normalized_email).first():
        raise HTTPException(status_code=400, detail=f"A user with email '{normalized_email}' already exists. Not modified.")
    user = User(
        full_name=payload.full_name.strip(),
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        department=payload.department.strip() if payload.department else None,
        is_active=payload.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return Token(access_token=token, must_change_password=user.must_change_password)

@router.post("/change-password", response_model=Token)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Self-service password change -- used both for the forced first-login flow
    (must_change_password=true) and any later voluntary change. Never accepts role or
    department, so a user can never change those about themselves here."""
    return UserAdminService.change_own_password(db, current_user=user, req=payload)
