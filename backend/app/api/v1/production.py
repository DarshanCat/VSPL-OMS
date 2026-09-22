from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.production_movement import ProductionMovement
from app.schemas.production import (
    MovePartsRequest, MovementResponse, MovementListItem,
    RecordStageProductionRequest, ProductionEntryResponse,
    WIPMatrixResponse, PlantReconciliationResponse
)
from app.services.production_service import ProductionService
from app.services.work_order_service import WorkOrderService
from app.services.oms_integration_service import OMSIntegrationService
from app.core.roles import PRODUCTION_ENTRY_ROLES

router = APIRouter(prefix="/api/v1/production", tags=["production"])

@router.post("/entry", response_model=ProductionEntryResponse)
def record_stage_production(
    payload: RecordStageProductionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PRODUCTION_ENTRY_ROLES))
):
    """Record production completion (Good Qty & Rejection Qty) at a stage without immediately moving material."""
    return ProductionService.record_stage_production(db, payload, current_user=user)

@router.post("/move", response_model=MovementResponse)
def move_parts(
    payload: MovePartsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Execute physical part movement between manufacturing stages with strict route, idempotency, and OMS WIP validation."""
    return ProductionService.move_parts(db, payload, current_user=user)

@router.get("/movements", response_model=List[MovementListItem])
def list_movements(
    wo_number: Optional[str] = Query(None, description="Filter by Work Order"),
    stage: Optional[str] = Query(None, description="Filter by stage"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve immutable production movement ledger history."""
    query = db.query(ProductionMovement)
    if wo_number:
        query = query.join(ProductionMovement.work_order).filter(ProductionMovement.work_order.has(wo_number=wo_number.strip()))
    if stage:
        query = query.filter((ProductionMovement.from_stage == stage.upper()) | (ProductionMovement.to_stage == stage.upper()))

    movs = query.order_by(ProductionMovement.created_at.desc()).offset(offset).limit(limit).all()
    results = []
    for m in movs:
        wo = m.work_order
        part = wo.order.part if (wo and wo.order) else None
        results.append(MovementListItem(
            id=str(m.id),
            movement_id=m.movement_id,
            client_request_id=m.client_request_id,
            source_type=m.source_type,
            wo_number=wo.wo_number if wo else "N/A",
            part_number=part.part_number if part else "N/A",
            part_name=part.description if part else None,
            from_stage=m.from_stage,
            to_stage=m.to_stage,
            quantity_moved=m.quantity_moved,
            rejected_quantity=m.rejected_quantity,
            machine_id=m.machine_id,
            operator_name=m.operator_name,
            shift=m.shift,
            movement_date=m.movement_date,
            movement_time=m.movement_time,
            remarks=m.remarks,
            created_by_name=m.creator.full_name if m.creator else None,
            created_at=m.created_at
        ))
    return results

@router.get("/wip", response_model=WIPMatrixResponse)
def get_wip_matrix(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve live stage-wise Work In Progress (WIP) matrix across all active work orders with InProc and OnHand breakdown."""
    return WorkOrderService.get_wip_matrix(db)

@router.get("/reconciliation", response_model=PlantReconciliationResponse)
def get_plant_reconciliation(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve authoritative manufacturing reconciliation verifying Released Qty == WIP + Rejections + Dispatched."""
    return OMSIntegrationService.reconcile_all_work_orders(db)
