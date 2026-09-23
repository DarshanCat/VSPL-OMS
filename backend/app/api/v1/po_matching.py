from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import require_roles
from app.models.user import User
from app.core.roles import PLANNING_ROLES
from app.schemas.master_data import MatchCandidate, DuplicateCheckResult, MatchConfirmRequest, MatchConfirmResponse
from app.services.po_matching_service import POMatchingService

router = APIRouter(prefix="/api/v1/po-matching", tags=["po-matching"])


@router.get("/check-duplicate", response_model=DuplicateCheckResult)
def check_duplicate(
    customer_code: str = Query(...),
    part_number: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    """Called before creating a new PO-based OAR: is there already a schedule-based
    OAR for this customer+part that should be matched instead?"""
    return POMatchingService.check_duplicate(db, customer_code, part_number)


@router.get("/candidates", response_model=List[MatchCandidate])
def get_candidates(
    po_line_id: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return POMatchingService.get_match_candidates(db, po_line_id)


@router.post("/match", response_model=MatchConfirmResponse)
def confirm_match(
    payload: MatchConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    return POMatchingService.confirm_match(db, payload, current_user=user)
