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
    CustomerPartOut, ResolveCustomerPartResponse,
    PartMasterCreate, PartMasterUpdate, PartMasterOut,
    PartMasterKPIs, PartMasterListResponse,
)
from app.services.master_data_service import (
    CustomerMasterService, POMasterService, ScheduleMasterService,
    list_customer_parts, resolve_customer_part_preview,
    PartMasterService,
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


# --- Customer Part Mapping (read-only lookups for the PO UI) ---

@router.get("/customer-parts", response_model=List[CustomerPartOut])
def get_customer_parts(
    customer_code: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return list_customer_parts(db, customer_code)


@router.get("/resolve-customer-part", response_model=ResolveCustomerPartResponse)
def resolve_customer_part_endpoint(
    customer_code: str = Query(...),
    customer_part_number: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return resolve_customer_part_preview(db, customer_code, customer_part_number)


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


# --- Part Master ---

@router.get("/parts/kpis", response_model=PartMasterKPIs)
def get_part_kpis(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return PartMasterService.get_kpis(db)


@router.get("/parts", response_model=PartMasterListResponse)
def list_parts(
    customer_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return PartMasterService.list_parts(
        db,
        customer_code=customer_code,
        status_filter=status,
        search=search,
        page=page,
        limit=limit,
    )


@router.get("/parts/{part_id}", response_model=PartMasterOut)
def get_part(
    part_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return PartMasterService.get_part(db, part_id=part_id)


@router.post("/parts", response_model=PartMasterOut)
def create_part(
    payload: PartMasterCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return PartMasterService.create_part(db, payload, current_user=user)


@router.put("/parts/{part_id}", response_model=PartMasterOut)
def update_part(
    part_id: str,
    payload: PartMasterUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return PartMasterService.update_part(db, part_id=part_id, req=payload, current_user=user)

