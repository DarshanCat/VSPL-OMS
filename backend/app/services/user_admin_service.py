from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.models.conversion_mapping import ConversionPartMapping
from app.models.customer_part_cross_reference import CustomerPartCrossReference
from app.models.dispatch import Dispatch
from app.models.machine import Machine
from app.models.master_data import POMaster, ScheduleMaster
from app.models.operator import Operator
from app.models.packing import PackingTransaction
from app.models.production import ProductionUpdate
from app.models.production_movement import ProductionMovement
from app.models.rejection_disposition import RejectionDisposition
from app.models.shift import Shift
from app.core.security import generate_temp_password, get_password_hash, verify_password, create_access_token, validate_company_email
from app.core.roles import USER_MANAGEMENT_ROLES
from app.schemas.auth import AdminUserCreate, TempPasswordResult, ChangePasswordRequest, UserOut, Token, UserDeleteResponse



def _require_admin(current_user: User, action_label: str) -> None:
    if current_user.role not in USER_MANAGEMENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role.value}' is not authorized to {action_label}.",
        )


def _audit(db: Session, actor: User, action: str, target: User, details: str = "") -> None:
    """Never records the password itself -- only that an action happened, by whom, on
    which account."""
    db.add(AuditLog(
        user_id=actor.id,
        user_name=actor.full_name,
        action=action,
        entity="User",
        entity_id=str(target.id),
        details=details,
    ))


class UserAdminService:
    @staticmethod
    def list_users(db: Session, current_user: User) -> List[UserOut]:
        _require_admin(current_user, "list user accounts")
        return db.query(User).order_by(User.email).all()

    @staticmethod
    def create_user(db: Session, req: AdminUserCreate, current_user: User) -> TempPasswordResult:
        _require_admin(current_user, "create a user account")

        normalized_email = validate_company_email(req.email)

        existing = db.query(User).filter(User.email == normalized_email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A user with email '{normalized_email}' already exists. Not modified.",
            )

        temp_password = generate_temp_password()
        user = User(
            full_name=req.full_name.strip(),
            email=normalized_email,
            hashed_password=get_password_hash(temp_password),
            role=req.role,
            department=req.department.strip() if req.department else None,
            is_active=True,
            must_change_password=True,
        )
        db.add(user)
        db.flush()
        _audit(db, current_user, "USER_CREATED", user, details=f"role={req.role.value}, department={req.department or ''}")
        db.commit()
        db.refresh(user)

        return TempPasswordResult(user=UserOut.model_validate(user), temporary_password=temp_password)

    @staticmethod
    def reset_password(db: Session, user_id: str, current_user: User) -> TempPasswordResult:
        _require_admin(current_user, "reset a user's password")

        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        temp_password = generate_temp_password()
        target.hashed_password = get_password_hash(temp_password)
        target.must_change_password = True
        _audit(db, current_user, "PASSWORD_RESET", target)
        db.commit()
        db.refresh(target)
        return TempPasswordResult(user=UserOut.model_validate(target), temporary_password=temp_password)

    @staticmethod
    def set_active(db: Session, user_id: str, is_active: bool, current_user: User) -> UserOut:
        _require_admin(current_user, "activate or deactivate a user account")

        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        target.is_active = is_active
        _audit(db, current_user, "USER_STATUS_CHANGED", target, details=f"is_active={is_active}")
        db.commit()
        db.refresh(target)
        return UserOut.model_validate(target)

    @staticmethod
    def _user_has_references(db: Session, user_id) -> bool:
        """Checks whether this user is referenced as a foreign key in any system table."""
        checks = [
            db.query(AuditLog.id).filter(AuditLog.user_id == user_id).first() is not None,
            db.query(ConversionPartMapping.id).filter((ConversionPartMapping.created_by_id == user_id) | (ConversionPartMapping.updated_by_id == user_id)).first() is not None,
            db.query(CustomerPartCrossReference.id).filter(CustomerPartCrossReference.created_by_id == user_id).first() is not None,
            db.query(Dispatch.id).filter(Dispatch.created_by == user_id).first() is not None,
            db.query(Machine.id).filter(Machine.created_by_id == user_id).first() is not None,
            db.query(POMaster.id).filter(POMaster.created_by_id == user_id).first() is not None,
            db.query(ScheduleMaster.id).filter(ScheduleMaster.created_by_id == user_id).first() is not None,
            db.query(Operator.id).filter((Operator.user_id == user_id) | (Operator.created_by_id == user_id)).first() is not None,
            db.query(PackingTransaction.id).filter(PackingTransaction.created_by == user_id).first() is not None,
            db.query(ProductionUpdate.id).filter(ProductionUpdate.operator_id == user_id).first() is not None,
            db.query(ProductionMovement.id).filter((ProductionMovement.operator_id == user_id) | (ProductionMovement.created_by == user_id)).first() is not None,
            db.query(RejectionDisposition.id).filter((RejectionDisposition.authorized_by_id == user_id) | (RejectionDisposition.melting_sent_by_id == user_id)).first() is not None,
            db.query(Shift.id).filter(Shift.created_by_id == user_id).first() is not None,
        ]
        return any(checks)

    @staticmethod
    def delete_user(db: Session, user_id: str, current_user: User) -> UserDeleteResponse:
        _require_admin(current_user, "delete a user account")

        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        if str(target.id) == str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrators cannot delete their own account.",
            )

        if target.role == UserRole.ADMIN and target.is_active:
            active_admin_count = db.query(User).filter(User.role == UserRole.ADMIN, User.is_active == True).count()
            if active_admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete the last active administrator account.",
                )

        if UserAdminService._user_has_references(db, target.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This user has historical records and cannot be permanently deleted. Deactivate the user instead.",
            )

        target_id_str = str(target.id)
        target_email = target.email
        target_role = target.role.value

        _audit(db, current_user, "USER_DELETED", target, details=f"email={target_email}, role={target_role}")
        db.delete(target)
        db.commit()

        return UserDeleteResponse(
            success=True,
            message=f"User '{target_email}' was permanently deleted.",
            user_id=target_id_str,
            email=target_email,
        )

    @staticmethod
    def change_own_password(db: Session, current_user: User, req: ChangePasswordRequest) -> Token:
        """Self-service only -- deliberately takes no role/department fields, so a user
        can never change their own role or department through this (or any) endpoint."""
        if not verify_password(req.current_password, current_user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect.")

        if len(req.new_password) < 8:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters.")
        if req.new_password == req.current_password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different from the current password.")

        current_user.hashed_password = get_password_hash(req.new_password)
        current_user.must_change_password = False
        _audit(db, current_user, "PASSWORD_CHANGED", current_user)
        db.commit()

        # Issue a fresh token: the old one may have been obtained while
        # must_change_password was true, and the temporary password it was issued
        # against no longer verifies against anything (the hash was just replaced).
        token = create_access_token({"sub": current_user.email, "role": current_user.role.value})
        return Token(access_token=token)

