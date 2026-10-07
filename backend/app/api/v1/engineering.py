from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.schemas.engineering import (
    EngineeringRevisionCreate,
    EngineeringRevisionUpdate,
    EngineeringRevisionOut,
    WOReadinessItemOut,
    WOReadinessDetailOut,
    WOReadinessChecklistUpdate,
    EngineeringReleaseRequest,
    EngineeringRevocationRequest,
    EngineeringReleaseResponse,
)
from app.services.engineering_service import EngineeringService
from app.core.roles import ENGINEERING_RELEASE_ROLES, USER_MANAGEMENT_ROLES

router = APIRouter(prefix="/api/v1/engineering", tags=["engineering"])


# ---------------------------------------------------------------------------
# Part Engineering Revision Master Endpoints
# ---------------------------------------------------------------------------

@router.get("/revisions", response_model=List[EngineeringRevisionOut])
def list_engineering_revisions(
    part_id: Optional[str] = Query(None, description="Filter by Part ID"),
    part_number: Optional[str] = Query(None, description="Filter by Part Number"),
    active_only: bool = Query(False, description="Filter active revisions only"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List reusable engineering profile / drawing revisions."""
    return EngineeringService.list_revisions(
        db,
        part_id=part_id,
        part_number=part_number,
        active_only=active_only
    )


@router.post("/revisions", response_model=EngineeringRevisionOut, status_code=status.HTTP_201_CREATED)
def create_engineering_revision(
    payload: EngineeringRevisionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ENGINEERING_RELEASE_ROLES))
):
    """Create a new engineering profile / drawing revision for a Part."""
    return EngineeringService.create_revision(db, payload, current_user=user)


@router.put("/revisions/{revision_id}", response_model=EngineeringRevisionOut)
def update_engineering_revision(
    revision_id: str,
    payload: EngineeringRevisionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ENGINEERING_RELEASE_ROLES))
):
    """Update an existing engineering profile / drawing revision."""
    return EngineeringService.update_revision(db, revision_id, payload, current_user=user)


# ---------------------------------------------------------------------------
# Work Order Engineering Readiness Endpoints
# ---------------------------------------------------------------------------

@router.get("/readiness", response_model=List[WOReadinessItemOut])
def list_wo_readiness(
    search: Optional[str] = Query(None, description="Search by WO, Customer, Part, PO, or OAR"),
    status_filter: Optional[str] = Query(None, description="Filter by readiness status (PENDING/READY/RELEASED/BLOCKED)"),
    customer_code: Optional[str] = Query(None, description="Filter by Customer Code"),
    classification: Optional[str] = Query(None, description="Filter by Order Classification (regular/npd)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List Work Order Engineering Readiness items with checklist completion progress."""
    return EngineeringService.list_readiness(
        db,
        search=search,
        status_filter=status_filter,
        customer_code=customer_code,
        classification=classification,
        limit=limit,
        offset=offset
    )


@router.get("/readiness/{wo_identifier}", response_model=WOReadinessDetailOut)
def get_wo_readiness_detail(
    wo_identifier: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve full engineering readiness detail and 6-point verification checklist for a WO."""
    return EngineeringService.get_readiness_detail(db, wo_identifier)


@router.put("/readiness/{wo_identifier}", response_model=WOReadinessDetailOut)
def update_wo_readiness_checklist(
    wo_identifier: str,
    payload: WOReadinessChecklistUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ENGINEERING_RELEASE_ROLES))
):
    """Update engineering verification checklist flags, drawing URL, pattern, tooling, and remarks."""
    return EngineeringService.update_checklist(db, wo_identifier, payload, current_user=user)


@router.post("/readiness/{wo_identifier}/release", response_model=EngineeringReleaseResponse)
def release_engineering(
    wo_identifier: str,
    payload: Optional[EngineeringReleaseRequest] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ENGINEERING_RELEASE_ROLES))
):
    """Authorize Engineering Release for a Work Order upon 100% verified checklist completion."""
    req = payload or EngineeringReleaseRequest()
    return EngineeringService.release_engineering(db, wo_identifier, req, current_user=user)


@router.post("/readiness/{wo_identifier}/revoke")
def revoke_engineering_release(
    wo_identifier: str,
    payload: EngineeringRevocationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN))
):
    """Revoke an Engineering Release prior to Manufacturing Release or first production entry (Admin only)."""
    return EngineeringService.revoke_engineering_release(db, wo_identifier, payload, current_user=user)
