from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User
from app.schemas.operations import (
    OrderIntakeCreate, OrderIntakeResponse,
    WOReleaseCreate, WOReleaseResponse,
    ConversionCreate, ConversionResponse,
    NCRecordCreate, NCRecordUpdate, NCRecordOut
)
from app.schemas.work_order import OARListItem
from app.services.operations_service import OperationsService
from app.services.work_order_service import WorkOrderService
from app.core.roles import PLANNING_ROLES, WO_RELEASE_ROLES, CONVERSION_MODULE_ROLES, QUALITY_APPROVAL_ROLES

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])

@router.post("/intake", response_model=OrderIntakeResponse)
def create_order_intake(
    payload: OrderIntakeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """Process incoming Order Intake (OAR) and create corresponding Work Orders.
    Planning-only per the OMS Roles & Responsibilities spec (Production Manager
    explicitly cannot create/edit an OAR)."""
    return OperationsService.create_order_intake(db, payload, current_user=user)

@router.get("/oars", response_model=List[OARListItem])
def list_oars(
    search: Optional[str] = Query(None, description="Search by OAR, customer, part, or PO"),
    status_filter: Optional[str] = Query(None, description="Filter by OAR status (accept/hold/reject)"),
    customer_code: Optional[str] = Query(None, description="Filter by customer code"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Read-only OAR & WO roll-up list/search for order intake tracking. Not a new
    business engine -- every figure is read directly from existing Order/WorkOrder/
    StageWIP/ProductionUpdate/Dispatch records."""
    return WorkOrderService.list_oars(
        db,
        search=search,
        status_filter=status_filter,
        customer_code=customer_code,
        limit=limit,
        offset=offset
    )

@router.post("/wo-release", response_model=WOReleaseResponse)
def release_work_order(
    payload: WOReleaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WO_RELEASE_ROLES))
):
    """Release a Work Order with physical quantity and custom stage routing."""
    return OperationsService.release_work_order(db, payload, current_user=user)

@router.post("/conversion", response_model=ConversionResponse)
def create_conversion(
    payload: ConversionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONVERSION_MODULE_ROLES))
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
    user: User = Depends(require_roles(*QUALITY_APPROVAL_ROLES))
):
    """Update NC status, root cause, or disposition (quality-approval action)."""
    return OperationsService.update_nc(db, payload, current_user=user)
