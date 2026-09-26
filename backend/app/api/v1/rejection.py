from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.core.roles import QUALITY_APPROVAL_ROLES
from app.models.user import User
from app.schemas.rejection import (
    ExcessNonMovingCreate, DispositionCreate, DispositionResponse,
    RejectionListItem, RejectionDetail, RejectionSummary, CWODetail,
    MeltingEntryCreate, MeltingEntryResponse,
    ReplacementCreate, ReplacementResponse,
    RejectionTypeCreate, RejectionTypeUpdate, RejectionTypeOut
)
from app.services.rejection_service import RejectionService, RejectionTypeService

router = APIRouter(prefix="/api/v1/rejection", tags=["rejection-tracking"])


# ---------------------------------------------------------------------------
# Rejection Type master. List is open to any authenticated user (Production
# Entry must be able to populate its dropdown) but only returns ACTIVE types
# unless the caller is in QUALITY_APPROVAL_ROLES and explicitly asks for
# inactive ones too -- mutation is QUALITY_APPROVAL_ROLES-only either way.
# ---------------------------------------------------------------------------

@router.get("/types", response_model=List[RejectionTypeOut])
def list_rejection_types(
    include_inactive: bool = Query(False, description="QUALITY/ADMIN only -- include deactivated types"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    if include_inactive and user.role not in QUALITY_APPROVAL_ROLES:
        include_inactive = False
    return RejectionTypeService.list_types(db, include_inactive=include_inactive)


@router.post("/types", response_model=RejectionTypeOut)
def create_rejection_type(
    payload: RejectionTypeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*QUALITY_APPROVAL_ROLES))
):
    return RejectionTypeService.create_type(db, payload, current_user=user)


@router.put("/types", response_model=RejectionTypeOut)
def update_rejection_type(
    payload: RejectionTypeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*QUALITY_APPROVAL_ROLES))
):
    """Update or deactivate a Rejection Type. Never physically deleted -- historical
    NCRecord.defect_code values are never rewritten and keep resolving regardless
    of active status."""
    return RejectionTypeService.update_type(db, payload, current_user=user)

@router.get("/cwo/{wo_number}", response_model=CWODetail)
def get_cwo_detail(
    wo_number: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Source lineage for a Conversion Work Order -- a normal Work Order created to
    execute a conversion. For its production progress, see the normal WO tracking page."""
    detail = RejectionService.get_cwo_detail(db, wo_number)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{wo_number}' was not found or was not created as a Conversion Work Order."
        )
    return detail

@router.get("", response_model=List[RejectionListItem])
def list_rejections(
    search: Optional[str] = Query(None),
    wo_number: Optional[str] = Query(None),
    oar_number: Optional[str] = Query(None),
    part_number: Optional[str] = Query(None),
    customer_code: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None, description="REJECTION | EXCESS_PRODUCTION | NON_MOVING | MANUAL"),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List rejection / excess / non-moving tracking records with full-text and field filters."""
    return RejectionService.list_rejections(
        db, search=search, wo_number=wo_number, oar_number=oar_number,
        part_number=part_number, customer_code=customer_code, stage=stage,
        source_type=source_type, status_filter=status_filter,
        date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )

@router.get("/summary", response_model=RejectionSummary)
def get_rejection_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Aggregate totals for the Rejection Tracking dashboard."""
    return RejectionService.get_summary(db)

@router.get("/{nc_number}", response_model=RejectionDetail)
def get_rejection_detail(
    nc_number: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Full source / disposition history / balance / final outcome for one record."""
    detail = RejectionService.get_rejection_detail(db, nc_number)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rejection Tracking record '{nc_number}' not found."
        )
    return detail

@router.post("/excess-non-moving", response_model=RejectionListItem)
def create_excess_or_non_moving(
    payload: ExcessNonMovingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Track excess production or non-moving material as a distinct source type,
    separate from a production rejection."""
    return RejectionService.create_excess_or_non_moving(db, payload, current_user=user)

@router.post("/disposition", response_model=DispositionResponse)
def create_disposition(
    payload: DispositionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Record a disposition decision (CONVERT_PART / SAME_PART / CWO / SCRAP /
    DEVIATION_ACCEPT) against a Rejection Tracking record. Authorization is enforced
    per-action inside the service, independent of any frontend restriction."""
    return RejectionService.create_disposition(db, payload, current_user=user)

@router.post("/replacement", response_model=ReplacementResponse)
def create_replacement(
    payload: ReplacementCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Quality marks a rejection as 'Replacement Required': creates a brand-new WO
    against the same OAR, linked back to the source WO. Never auto-generated from a
    rejection entry -- only ever created by this explicit action -- and never
    auto-released; it must follow the normal Engineering/Manufacturing/WO release
    chain before production. Authorization (QUALITY_APPROVAL_ROLES) is enforced inside
    the service, independent of any frontend restriction."""
    return RejectionService.create_replacement(db, payload, current_user=user)

@router.post("/melting-entry", response_model=MeltingEntryResponse)
def record_melting_entry(
    payload: MeltingEntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Physical material-handling entry: record that an already-decided SCRAP
    disposition's material was sent for melting. This is execution of an existing
    decision, not a new disposition authority -- allowed for STORE and the existing
    QUALITY_OVERSIGHT_ROLES, enforced inside the service."""
    return RejectionService.record_melting_entry(db, payload, current_user=user)
