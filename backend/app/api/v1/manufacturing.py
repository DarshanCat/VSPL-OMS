from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.core.roles import MANUFACTURING_RELEASE_ROLES
from app.models.user import User, UserRole
from app.services.manufacturing_service import ManufacturingService
from app.schemas.manufacturing import (
    ManufacturingKPIs,
    WOManufacturingReadinessItemOut,
    WOManufacturingReadinessDetailOut,
    WOManufacturingReadinessUpdate,
    ManufacturingReleaseRequest,
    ManufacturingRevocationRequest,
    ManufacturingReleaseResponse,
)

router = APIRouter(prefix="/api/v1/manufacturing", tags=["manufacturing"])


@router.get("/kpis", response_model=ManufacturingKPIs)
def get_manufacturing_kpis(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve live manufacturing readiness KPI counts (Pending, Ready, Released, Blocked, Replacements)."""
    return ManufacturingService.get_kpis(db)


@router.get("/readiness", response_model=List[WOManufacturingReadinessItemOut])
def list_manufacturing_readiness(
    status: Optional[str] = Query(None, description="Filter by readiness status: PENDING, READY, RELEASED, BLOCKED"),
    order_type: Optional[str] = Query(None, description="Filter by order type: REGULAR, NPD"),
    search: Optional[str] = Query(None, description="Search query by WO number, part name, customer"),
    is_replacement: Optional[bool] = Query(None, description="Filter by replacement Work Orders"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve filterable Work Order manufacturing readiness queue."""
    return ManufacturingService.list_readiness(
        db,
        status_filter=status,
        order_type_filter=order_type,
        search=search,
        is_replacement_filter=is_replacement,
        skip=skip,
        limit=limit,
    )


@router.get("/readiness/{wo_identifier}", response_model=WOManufacturingReadinessDetailOut)
def get_manufacturing_readiness_detail(
    wo_identifier: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve full manufacturing readiness detail and checklist for a specific Work Order."""
    return ManufacturingService.get_readiness_detail(db, wo_identifier)


@router.put("/readiness/{wo_identifier}", response_model=WOManufacturingReadinessDetailOut)
def update_manufacturing_readiness(
    wo_identifier: str,
    payload: WOManufacturingReadinessUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANUFACTURING_RELEASE_ROLES)),
):
    """Update manufacturing readiness checklist items, remarks, machine allocation, or operator assignment."""
    return ManufacturingService.update_readiness(db, wo_identifier, payload, current_user=user)


@router.post("/release/{wo_identifier}", response_model=ManufacturingReleaseResponse)
def release_manufacturing(
    wo_identifier: str,
    payload: ManufacturingReleaseRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANUFACTURING_RELEASE_ROLES)),
):
    """Authorize Manufacturing Release for a Work Order (Requires 6/6 readiness checks and prior Engineering Release)."""
    return ManufacturingService.release_manufacturing(db, wo_identifier, payload, current_user=user)


@router.post("/revoke/{wo_identifier}", response_model=ManufacturingReleaseResponse)
def revoke_manufacturing_release(
    wo_identifier: str,
    payload: ManufacturingRevocationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Revoke a Manufacturing Release prior to shop-floor production movement (Admin only)."""
    return ManufacturingService.revoke_manufacturing_release(db, wo_identifier, payload, current_user=user)
