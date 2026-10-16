from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User
from app.core.roles import MRB_ROLES
from app.schemas.mrb import (
    MRBReviewItem,
    MRBReviewDecisionRequest,
    MRBListResponse,
    MRBDecisionResponse
)
from app.services.mrb_service import MRBService

router = APIRouter(prefix="/api/v1/mrb", tags=["mrb"])


@router.get("/reviews", response_model=MRBListResponse)
def list_mrb_reviews(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: PENDING, APPROVED, ADJUSTED, REJECTED, ALL"),
    stage: Optional[str] = Query(None, description="Filter by stage code e.g. F1, F2, SP, FI"),
    wo_number: Optional[str] = Query(None, description="Filter by Work Order number"),
    search: Optional[str] = Query(None, description="Search MRB tickets, WOs, operators, heats"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List Material Review Board tickets with KPI totals and search/filter support."""
    return MRBService.list_reviews(
        db=db,
        status_filter=status_filter,
        stage=stage,
        wo_number=wo_number,
        search=search,
        limit=limit,
        offset=offset
    )


@router.get("/reviews/{review_id}", response_model=MRBReviewItem)
def get_mrb_review(
    review_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get single MRB ticket details."""
    return MRBService.get_review(db=db, review_id=review_id)


@router.post("/reviews/{review_id}/decision", response_model=MRBDecisionResponse)
def record_mrb_decision(
    review_id: str,
    payload: MRBReviewDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MRB_ROLES))
):
    """Quality, Planner, and Admin verification decision: Approve, Adjust, or Reject."""
    return MRBService.process_review_decision(
        db=db,
        review_id=review_id,
        req=payload,
        current_user=user
    )


@router.post("/reviews/{review_id}/approve", response_model=MRBDecisionResponse)
def approve_mrb_review(
    review_id: str,
    payload: Optional[MRBReviewDecisionRequest] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MRB_ROLES))
):
    """Quick approve endpoint confirming shop floor reported quantities."""
    req = payload or MRBReviewDecisionRequest(action="APPROVE")
    req.action = "APPROVE"
    return MRBService.process_review_decision(
        db=db,
        review_id=review_id,
        req=req,
        current_user=user
    )


@router.post("/reviews/{review_id}/adjust", response_model=MRBDecisionResponse)
def adjust_mrb_review(
    review_id: str,
    payload: MRBReviewDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MRB_ROLES))
):
    """Adjust shop floor quantities upon physical quality verification."""
    payload.action = "ADJUST"
    return MRBService.process_review_decision(
        db=db,
        review_id=review_id,
        req=payload,
        current_user=user
    )
