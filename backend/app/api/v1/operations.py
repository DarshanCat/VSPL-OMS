from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.schemas.operations import (
    OrderIntakeCreate, OrderIntakeResponse,
    WOReleaseCreate, WOReleaseResponse,
    ConversionCreate, ConversionResponse,
    NCRecordCreate, NCRecordUpdate, NCRecordOut
)
from app.services.operations_service import OperationsService

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])

# Same role grouping already used for the OMS planning cycle (app/api/v1/oms.py
# ALLOWED_ROLES) -- WO release and conversion are the same class of planning/release
# decision, not open shop-floor actions.
PLANNING_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.PRODUCTION_MANAGER)

# Same role grouping already used for audit-log access (app/api/v1/admin.py) -- NC
# disposition is an oversight/quality-approval action, the same class of action.
QUALITY_OVERSIGHT_ROLES = (UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.QA, UserRole.CEO)

@router.post("/intake", response_model=OrderIntakeResponse)
def create_order_intake(
    payload: OrderIntakeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Process incoming Order Intake (OAR) and create corresponding Work Orders."""
    return OperationsService.create_order_intake(db, payload, current_user=user)

@router.post("/wo-release", response_model=WOReleaseResponse)
def release_work_order(
    payload: WOReleaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """Release a Work Order with physical quantity and custom stage routing."""
    return OperationsService.release_work_order(db, payload, current_user=user)

@router.post("/conversion", response_model=ConversionResponse)
def create_conversion(
    payload: ConversionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """Execute part conversion between Work Orders with route debit validation."""
    return OperationsService.create_conversion(db, payload, current_user=user)

@router.get("/nc", response_model=List[NCRecordOut])
def get_nc_records(
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all QA Non-Conformance records."""
    return OperationsService.get_nc_records(db, limit=limit, offset=offset)

@router.post("/nc", response_model=NCRecordOut)
def create_nc_record(
    payload: NCRecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Log a new QA Non-Conformance defect report."""
    return OperationsService.create_nc(db, payload, current_user=user)

@router.put("/nc", response_model=NCRecordOut)
def update_nc_record(
    payload: NCRecordUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*QUALITY_OVERSIGHT_ROLES))
):
    """Update NC status, root cause, or disposition (quality-approval action)."""
    return OperationsService.update_nc(db, payload, current_user=user)
