from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User
from app.schemas.vendor import (
    VendorDispatchItem,
    VendorReceiveRequest,
    VendorReceiveResponse,
    VendorSummaryResponse
)
from app.services.vendor_service import VendorService
from app.core.roles import PRODUCTION_ENTRY_ROLES, MATERIAL_MOVEMENT_ROLES

router = APIRouter(prefix="/api/v1/vendor", tags=["vendor-tracking"])


@router.get("/dispatches", response_model=List[VendorDispatchItem])
def list_vendor_dispatches(
    status: Optional[str] = Query(None, description="Filter by status: AT_VENDOR, PARTIALLY_RECEIVED, RECEIVED, ALL"),
    search: Optional[str] = Query(None, description="Search by DC#, Vendor Name, WO#, Part, Customer"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Lists all Work Orders dispatched to outside subcontractors / vendors."""
    return VendorService.list_dispatches(
        db, status_filter=status, search=search, limit=limit, offset=offset
    )


@router.get("/summary", response_model=VendorSummaryResponse)
def get_vendor_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Aggregate totals for active vendor dispatches, pieces at vendor, and returns."""
    return VendorService.get_summary(db)


@router.post("/receive", response_model=VendorReceiveResponse)
def receive_from_vendor(
    payload: VendorReceiveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MATERIAL_MOVEMENT_ROLES))
):
    """Receives subcontracted parts returned from a vendor and lands them directly
    into FI (Final Inspection) StageWIP, bypassing intermediate in-house stages."""
    return VendorService.receive_from_vendor(
        db=db,
        dispatch_id=payload.dispatch_id,
        received_qty=payload.received_qty,
        scrap_qty=payload.scrap_qty,
        inward_dc=payload.inward_dc,
        remarks=payload.remarks,
        current_user=user
    )
