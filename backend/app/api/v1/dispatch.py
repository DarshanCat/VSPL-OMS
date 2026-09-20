from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.schemas.dispatch import DispatchQueueItem, DispatchRequest, DispatchResponse, DispatchHistoryItem
from app.services.dispatch_service import DispatchService

router = APIRouter(prefix="/api/v1/dispatch", tags=["dispatch"])

# DISPATCH is the role that exists specifically for this function; ADMIN and
# PRODUCTION_MANAGER are included for oversight/exception handling, matching the
# existing "domain role + management oversight" pattern used for the OMS planning
# cycle (app/api/v1/oms.py) and audit-log access (app/api/v1/admin.py).
DISPATCH_ROLES = (UserRole.DISPATCH, UserRole.PRODUCTION_MANAGER, UserRole.ADMIN)

@router.get("/queue", response_model=List[DispatchQueueItem])
def get_dispatch_queue(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve queue of Work Orders that have verified ready-for-dispatch quantities."""
    return DispatchService.get_dispatch_queue(db)

@router.post("/ship", response_model=DispatchResponse)
def execute_dispatch(
    payload: DispatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*DISPATCH_ROLES))
):
    """Execute dispatch shipment with strict validation against packing-ready inventory."""
    return DispatchService.execute_dispatch(db, payload, current_user=user)

@router.get("/history", response_model=List[DispatchHistoryItem])
def get_dispatch_history(
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve immutable dispatch transaction history with invoice details."""
    return DispatchService.get_dispatch_history(db, limit=limit, offset=offset)
