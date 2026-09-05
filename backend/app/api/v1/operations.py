from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.operations import (
    OrderIntakeCreate, OrderIntakeResponse,
    WOReleaseCreate, WOReleaseResponse,
    ConversionCreate, ConversionResponse,
    NCRecordCreate, NCRecordUpdate, NCRecordOut
)
from app.services.operations_service import OperationsService

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])

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
    user: User = Depends(get_current_user)
):
    """Release a Work Order with physical quantity and custom stage routing."""
    return OperationsService.release_work_order(db, payload, current_user=user)

@router.post("/conversion", response_model=ConversionResponse)
def create_conversion(
    payload: ConversionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Execute part conversion between Work Orders with route debit validation."""
    return OperationsService.create_conversion(db, payload, current_user=user)

@router.get("/nc", response_model=List[NCRecordOut])
def get_nc_records(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all QA Non-Conformance records."""
    return OperationsService.get_nc_records(db)

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
    user: User = Depends(get_current_user)
):
    """Update NC status, root cause, or disposition."""
    return OperationsService.update_nc(db, payload, current_user=user)
