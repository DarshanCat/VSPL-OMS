from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import require_roles
from app.models.user import User
from app.core.roles import PLANNING_ROLES
from app.schemas.master_data import (
    CustomerCreate, CustomerUpdate, CustomerOut,
    POMasterCreate, POMasterOut,
    ScheduleCreate, ScheduleOut,
)
from app.services.master_data_service import CustomerMasterService, POMasterService, ScheduleMasterService

router = APIRouter(prefix="/api/v1/masters", tags=["masters"])


# --- Customer Master ---

@router.get("/customers", response_model=List[CustomerOut])
def list_customers(db: Session = Depends(get_db), user: User = Depends(require_roles(*PLANNING_ROLES))):
    return CustomerMasterService.list_customers(db)


@router.post("/customers", response_model=CustomerOut)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return CustomerMasterService.create_customer(db, payload, current_user=user)


@router.put("/customers", response_model=CustomerOut)
def update_customer(
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return CustomerMasterService.update_customer(db, payload, current_user=user)


# --- PO Master ---

@router.get("/pos", response_model=List[POMasterOut])
def list_pos(
    customer_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return POMasterService.list_pos(db, customer_code=customer_code)


@router.post("/pos", response_model=POMasterOut)
def create_po(
    payload: POMasterCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return POMasterService.create_po(db, payload, current_user=user)


# --- Schedule Master ---

@router.get("/schedules", response_model=List[ScheduleOut])
def list_schedules(
    customer_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return ScheduleMasterService.list_schedules(db, customer_code=customer_code)


@router.post("/schedules", response_model=ScheduleOut)
def create_schedule(
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return ScheduleMasterService.create_schedule(db, payload, current_user=user)
