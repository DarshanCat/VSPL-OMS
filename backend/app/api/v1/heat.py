from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.core.roles import HEAT_MANAGEMENT_ROLES, HEAT_ALLOCATION_ROLES
from app.models.user import User
from app.schemas.heat import (
    HeatCreate, HeatResponse,
    HeatAllocationCreate, WOHeatAllocationResponse,
    TraceabilityResponse
)
from app.services.heat_service import HeatService

router = APIRouter(prefix="/api/v1/heats", tags=["Heat Traceability"])
wo_heat_router = APIRouter(prefix="/api/v1/work-orders", tags=["Heat Traceability"])

@router.get("", response_model=List[HeatResponse])
def list_heats(
    grade: Optional[str] = Query(None, description="Filter by metallurgy grade"),
    status: Optional[str] = Query(None, description="Filter by status (ACTIVE, DEPLETED, QUARANTINED)"),
    search: Optional[str] = Query(None, description="Search heat number, grade, or TC"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all furnace heat melt batches with allocated quantity totals."""
    return HeatService.get_heats(
        db,
        grade=grade,
        status_filter=status,
        search=search,
        limit=limit,
        offset=offset
    )


@router.post("", response_model=HeatResponse, status_code=201)
def create_heat(
    req: HeatCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*HEAT_MANAGEMENT_ROLES))
):
    """Create a new furnace melt / heat batch record with metallurgy grade and optional TC number."""
    return HeatService.create_heat(db, req, current_user=current_user)


@wo_heat_router.post("/{wo_number}/heat-allocations", response_model=WOHeatAllocationResponse)
def allocate_heats_to_work_order(
    wo_number: str = Path(..., description="Target Work Order number"),
    req: HeatAllocationCreate = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*HEAT_ALLOCATION_ROLES))
):
    """Allocate pieces from one or more furnace heats to a Work Order (M:N consumption)."""
    return HeatService.allocate_heats_to_wo(
        db,
        wo_number=wo_number,
        req=req,
        current_user=current_user
    )


@wo_heat_router.get("/{wo_number}/traceability", response_model=TraceabilityResponse)
def get_work_order_traceability(
    wo_number: str = Path(..., description="Target Work Order number"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Authoritative end-to-end manufacturing pedigree: Customer PO -> OAR -> WO -> Heats -> Stages -> Dispatches."""
    return HeatService.get_wo_traceability(db, wo_number=wo_number)
