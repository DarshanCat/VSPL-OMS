from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import require_roles
from app.models.user import User
from app.core.roles import PLANNING_ROLES
from app.schemas.conversion_mapping import ConversionMappingCreate, ConversionMappingUpdate, ConversionMappingOut
from app.services.conversion_mapping_service import ConversionMappingService

router = APIRouter(prefix="/api/v1/conversion-mapping", tags=["conversion-mapping"])

@router.get("", response_model=List[ConversionMappingOut])
def list_conversion_mappings(
    source_part_number: Optional[str] = Query(None),
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """The authoritative Source Part -> Destination Part conversion master. Nothing here
    is invented -- every row is created explicitly by an authorized planner/admin."""
    return ConversionMappingService.list_mappings(db, source_part_number=source_part_number, active_only=active_only)

@router.post("", response_model=ConversionMappingOut)
def create_conversion_mapping(
    payload: ConversionMappingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """Define a new approved Source Part -> Destination Part conversion relationship."""
    return ConversionMappingService.create_mapping(db, payload, current_user=user)

@router.put("", response_model=ConversionMappingOut)
def update_conversion_mapping(
    payload: ConversionMappingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """Activate/deactivate an existing mapping or adjust its conversion factor."""
    return ConversionMappingService.update_mapping(db, payload, current_user=user)
