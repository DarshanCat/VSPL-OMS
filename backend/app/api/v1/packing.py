from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.core.roles import PACKING_ROLES
from app.models.user import User
from app.schemas.packing import PackingQueueItem, PackingUpdateRequest, PackingUpdateResponse
from app.services.packing_service import PackingService

router = APIRouter(prefix="/api/v1/packing", tags=["packing"])

@router.get("/queue", response_model=List[PackingQueueItem])
def get_packing_queue(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve queue of Work Orders at Packing / BSR stage."""
    return PackingService.get_packing_queue(db)

@router.post("/update", response_model=PackingUpdateResponse)
def update_packing(
    payload: PackingUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PACKING_ROLES))
):
    """Record completed packing / BSR quantities and make them available for dispatch."""
    return PackingService.update_packing(db, payload, current_user=user)
