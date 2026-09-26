from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import require_roles, get_current_user
from app.models.user import User
from app.core.roles import PLANNING_ROLES
from app.schemas.master_data import (
    CustomerCreate, CustomerUpdate, CustomerOut,
    POMasterCreate, POMasterOut,
    ScheduleCreate, ScheduleOut,
    MachineCreate, MachineUpdate, MachineOut,
    ShiftCreate, ShiftUpdate, ShiftOut,
    OperatorCreate, OperatorUpdate, OperatorOut,
)
from app.services.master_data_service import (
    CustomerMasterService, POMasterService, ScheduleMasterService,
    MachineMasterService, ShiftMasterService, OperatorMasterService,
)

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


# --- Machine Master ---
# Unlike Customer/PO/Schedule (genuinely planning-only data), Machine/Shift/Operator
# are selected by shop-floor roles in Production Entry -- so, deliberately deviating
# from this file's usual "PLANNING_ROLES gates read too" convention, listing is open
# to any authenticated user while mutation stays PLANNING_ROLES-only.

@router.get("/machines", response_model=List[MachineOut])
def list_machines(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return MachineMasterService.list_machines(db)


@router.post("/machines", response_model=MachineOut)
def create_machine(
    payload: MachineCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return MachineMasterService.create_machine(db, payload, current_user=user)


@router.put("/machines", response_model=MachineOut)
def update_machine(
    payload: MachineUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return MachineMasterService.update_machine(db, payload, current_user=user)


# --- Shift Master ---

@router.get("/shifts", response_model=List[ShiftOut])
def list_shifts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ShiftMasterService.list_shifts(db)


@router.post("/shifts", response_model=ShiftOut)
def create_shift(
    payload: ShiftCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return ShiftMasterService.create_shift(db, payload, current_user=user)


@router.put("/shifts", response_model=ShiftOut)
def update_shift(
    payload: ShiftUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return ShiftMasterService.update_shift(db, payload, current_user=user)


# --- Operator Master ---

@router.get("/operators", response_model=List[OperatorOut])
def list_operators(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return OperatorMasterService.list_operators(db)


@router.post("/operators", response_model=OperatorOut)
def create_operator(
    payload: OperatorCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return OperatorMasterService.create_operator(db, payload, current_user=user)


@router.put("/operators", response_model=OperatorOut)
def update_operator(
    payload: OperatorUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return OperatorMasterService.update_operator(db, payload, current_user=user)
