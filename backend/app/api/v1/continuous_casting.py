"""Continuous Casting (China) write API -- a deliberately thin adapter over the existing, already-tested services.

    HTTP request -> schema validation -> authentication / role dependency -> China service -> response

This module contains NO business logic. The services stay authoritative for validation, authorization,
transactions, commit, audit, idempotency and every business rule: a router function only passes the validated
payload and the authenticated user to its service and returns the service's own response model. Nothing here
commits, rolls back, queries or writes the database, and no service HTTPException is caught or rewritten.

Roles: each endpoint uses require_roles(<the frozen CC_* tuple>) like every other router (401 without a valid
token, 403 for the wrong role). The service still checks the role again; that duplication is intentional and the
service remains the final authority. The one read here (a material) needs only an authenticated user.

Endpoint contract notes:
  * A few URLs carry an id in the path (a material, an inward, a routing to release). Their service request
    objects hold that id, so the body models (CCMaterialPatch, CCInwardQADecisionBody, CCRoutingReleaseBody) omit
    it and the router builds the full request from the path id and the validated body.
  * Superseding a routing is POST /routings/supersede: the service identifies the routing to supersede by the
    request's wo_number (the Work Order's ACTIVE routing) and has no routing-id input, so a routing id in the
    path would be ignored. The path therefore mirrors the service contract instead of implying otherwise.
"""
import uuid
from datetime import datetime
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.roles import (
    CC_ADJUSTMENT_ROLES, CC_CUT_ROLES, CC_HOLD_RELEASE_ROLES, CC_HOLD_ROLES, CC_INWARD_ROLES, CC_ISSUE_ROLES,
    CC_MATERIAL_MASTER_ROLES, CC_QA_ROLES, CC_RESERVE_ROLES, CC_ROUTING_ROLES, CC_SCRAP_ROLES,
)
from app.models.user import User
from app.schemas.continuous_casting import (
    CCAdjustmentCreate, CCAllocationCreate, CCAllocationResult, CCCutConsumeCreate, CCCutResultCreate,
    CCCutResultResult, CCHoldCreate, CCHoldReleaseCreate, CCInwardCreate, CCInwardQADecisionBody,
    CCInwardQADecisionCreate, CCInwardQADecisionResult, CCInwardResult, CCIssueCreate, CCMaterialCreate,
    CCMaterialPatch, CCMaterialResult, CCMaterialUpdate, CCReleaseCreate, CCReserveCreate, CCReturnCreate,
    CCRoutingCreate, CCRoutingReleaseBody, CCRoutingReleaseCreate, CCRoutingReleaseResult, CCRoutingResult,
    CCRoutingSupersede, CCScrapCreate, CCSplitCreate, CCSplitResult, CCStockMovementResult, CCUnitMovementResult,
)
from app.schemas.continuous_casting_read import (
    CCAllocationListResponse, CCCutAvailableListResponse, CCCutResultListResponse, CCCutResultOut, CCGateStatus,
    CCInwardDetail, CCInwardListResponse, CCLedgerListResponse, CCMaterialListResponse,
    CCMaterialStockSummaryResponse, CCRoutingDetail, CCRoutingListResponse, CCStockUnitDetail,
    CCStockUnitListResponse, CCTraceInward, CCTraceWorkOrder,
)
from app.services.continuous_casting_cut_service import ContinuousCastingCutService
from app.services.continuous_casting_material_service import ContinuousCastingMaterialService
from app.services.continuous_casting_physical_service import ContinuousCastingPhysicalService
from app.services.continuous_casting_qa_service import ContinuousCastingQAService
from app.services.continuous_casting_read_service import ContinuousCastingReadService
from app.services.continuous_casting_reservation_service import ContinuousCastingReservationService
from app.services.continuous_casting_routing_service import (
    ContinuousCastingAllocationService, ContinuousCastingRoutingService,
)
from app.services.continuous_casting_service import ContinuousCastingInwardService
from app.services.continuous_casting_split_service import ContinuousCastingSplitService

router = APIRouter(prefix="/api/v1/continuous-casting", tags=["continuous-casting"])


# ------------------------------------------------------------------ material master
@router.post("/materials", response_model=CCMaterialResult)
def create_material(
    payload: CCMaterialCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_MATERIAL_MASTER_ROLES)),
):
    return ContinuousCastingMaterialService.create_material(db, payload, current_user=user)


@router.patch("/materials/{material_id}", response_model=CCMaterialResult)
def update_material(
    material_id: uuid.UUID,
    payload: CCMaterialPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_MATERIAL_MASTER_ROLES)),
):
    request = CCMaterialUpdate(material_id=material_id, **payload.model_dump(exclude_unset=True))
    return ContinuousCastingMaterialService.update_material(db, request, current_user=user)


@router.get("/materials/{material_id}", response_model=CCMaterialResult)
def get_material(
    material_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingMaterialService.get_material(db, material_id)


# ------------------------------------------------------------------ inward and its QA decision
@router.post("/inwards", response_model=CCInwardResult)
def create_inward(
    payload: CCInwardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_INWARD_ROLES)),
):
    return ContinuousCastingInwardService.create_inward(db, payload, current_user=user)


@router.post("/inwards/{inward_id}/qa", response_model=CCInwardQADecisionResult)
def decide_inward_qa(
    inward_id: uuid.UUID,
    payload: CCInwardQADecisionBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_QA_ROLES)),
):
    request = CCInwardQADecisionCreate(inward_id=inward_id, **payload.model_dump())
    return ContinuousCastingQAService.decide(db, request, current_user=user)


# ------------------------------------------------------------------ routing and allocation
@router.post("/routings", response_model=CCRoutingResult)
def create_routing(
    payload: CCRoutingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_ROUTING_ROLES)),
):
    return ContinuousCastingRoutingService.create_routing(db, payload, current_user=user)


@router.post("/routings/supersede", response_model=CCRoutingResult)
def supersede_routing(
    payload: CCRoutingSupersede,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_ROUTING_ROLES)),
):
    return ContinuousCastingRoutingService.supersede_routing(db, payload, current_user=user)


@router.post("/allocations", response_model=CCAllocationResult)
def create_allocation(
    payload: CCAllocationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_RESERVE_ROLES)),
):
    return ContinuousCastingAllocationService.create_allocation(db, payload, current_user=user)


# ------------------------------------------------------------------ reservation / release
@router.post("/reservations", response_model=CCStockMovementResult)
def reserve(
    payload: CCReserveCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_RESERVE_ROLES)),
):
    return ContinuousCastingReservationService.reserve(db, payload, current_user=user)


@router.post("/reservations/release", response_model=CCStockMovementResult)
def release(
    payload: CCReleaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_RESERVE_ROLES)),
):
    return ContinuousCastingReservationService.release(db, payload, current_user=user)


@router.post("/routings/{routing_id}/release-superseded", response_model=CCRoutingReleaseResult)
def release_superseded_routing(
    routing_id: uuid.UUID,
    payload: CCRoutingReleaseBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_RESERVE_ROLES)),
):
    request = CCRoutingReleaseCreate(routing_id=routing_id, reason=payload.reason)
    return ContinuousCastingReservationService.release_superseded_routing(db, request, current_user=user)


# ------------------------------------------------------------------ physical stock movements
@router.post("/issues", response_model=CCStockMovementResult)
def issue(
    payload: CCIssueCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_ISSUE_ROLES)),
):
    return ContinuousCastingReservationService.issue(db, payload, current_user=user)


@router.post("/cut-consume", response_model=CCStockMovementResult)
def cut_consume(
    payload: CCCutConsumeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_CUT_ROLES)),
):
    return ContinuousCastingReservationService.cut_consume(db, payload, current_user=user)


@router.post("/returns", response_model=CCStockMovementResult)
def return_stock(
    payload: CCReturnCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_ISSUE_ROLES)),
):
    return ContinuousCastingReservationService.return_stock(db, payload, current_user=user)


@router.post("/splits", response_model=CCSplitResult)
def split(
    payload: CCSplitCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_ISSUE_ROLES)),
):
    return ContinuousCastingSplitService.split(db, payload, current_user=user)


@router.post("/holds", response_model=CCUnitMovementResult)
def hold(
    payload: CCHoldCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_HOLD_ROLES)),
):
    return ContinuousCastingPhysicalService.hold(db, payload, current_user=user)


@router.post("/holds/release", response_model=CCUnitMovementResult)
def hold_release(
    payload: CCHoldReleaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_HOLD_RELEASE_ROLES)),
):
    return ContinuousCastingPhysicalService.hold_release(db, payload, current_user=user)


@router.post("/scrap", response_model=CCUnitMovementResult)
def scrap(
    payload: CCScrapCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_SCRAP_ROLES)),
):
    return ContinuousCastingPhysicalService.scrap(db, payload, current_user=user)


@router.post("/adjustments/out", response_model=CCUnitMovementResult)
def adjust_out(
    payload: CCAdjustmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_ADJUSTMENT_ROLES)),
):
    return ContinuousCastingPhysicalService.adjust_out(db, payload, current_user=user)


@router.post("/adjustments/in", response_model=CCUnitMovementResult)
def adjust_in(
    payload: CCAdjustmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_ADJUSTMENT_ROLES)),
):
    return ContinuousCastingPhysicalService.adjust_in(db, payload, current_user=user)


# ------------------------------------------------------------------ cut result
@router.post("/cut-results", response_model=CCCutResultResult)
def record_cut_result(
    payload: CCCutResultCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CC_CUT_ROLES)),
):
    return ContinuousCastingCutService.record_cut_result(db, payload, current_user=user)


# ====================================================================================================
# READ API (Phase 11C). Every read needs only an authenticated user (get_current_user); each handler is one call
# to the read-only service, which owns every query. Lists return {items, total, limit, offset}.
# ====================================================================================================
MovementType = Literal[
    "INWARD", "RESERVE", "RELEASE", "ISSUE", "CUT_CONSUME", "RETURN", "HOLD", "HOLD_RELEASE", "SCRAP",
    "ADJUSTMENT_IN", "ADJUSTMENT_OUT", "SPLIT_OUT", "SPLIT_IN",
]


@router.get("/materials", response_model=CCMaterialListResponse)
def list_materials(
    search: Optional[str] = Query(None, max_length=100),
    is_active: Optional[bool] = Query(None),
    grade: Optional[str] = Query(None, max_length=100),
    section: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.list_materials(
        db, search=search, is_active=is_active, grade=grade, section=section, limit=limit, offset=offset)


@router.get("/inwards", response_model=CCInwardListResponse)
def list_inwards(
    inward_number: Optional[str] = Query(None, max_length=100),
    material_id: Optional[uuid.UUID] = Query(None),
    qa_status: Optional[Literal["PENDING_QA", "ACCEPTED", "REJECTED", "ON_HOLD"]] = Query(None),
    location: Optional[str] = Query(None, max_length=100),
    received_from: Optional[datetime] = Query(None),
    received_to: Optional[datetime] = Query(None),
    has_free_stock: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.list_inwards(
        db, inward_number=inward_number, material_id=material_id, qa_status=qa_status, location=location,
        received_from=received_from, received_to=received_to, has_free_stock=has_free_stock, limit=limit,
        offset=offset)


@router.get("/inwards/{inward_id}", response_model=CCInwardDetail)
def get_inward(
    inward_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.get_inward(db, inward_id)


@router.get("/stock-summary", response_model=CCMaterialStockSummaryResponse)
def list_material_stock_summary(
    search: Optional[str] = Query(None, max_length=100),
    grade: Optional[str] = Query(None, max_length=100),
    section: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, max_length=40),
    location: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.list_material_stock_summary(
        db, search=search, grade=grade, section=section, status_filter=status,
        location=location, limit=limit, offset=offset)


@router.get("/stock-units", response_model=CCStockUnitListResponse)
def list_stock_units(
    inward_id: Optional[uuid.UUID] = Query(None),
    material_id: Optional[uuid.UUID] = Query(None),
    status: Optional[Literal["IN_STOCK", "ON_HOLD", "CONSUMED", "SCRAPPED"]] = Query(None),
    location: Optional[str] = Query(None, max_length=100),
    on_hold: Optional[bool] = Query(None),
    available: Optional[bool] = Query(None),
    parent_unit_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.list_stock_units(
        db, inward_id=inward_id, material_id=material_id, status_filter=status, location=location,
        on_hold=on_hold, available=available, parent_unit_id=parent_unit_id, limit=limit, offset=offset)


@router.get("/stock-units/{unit_id}", response_model=CCStockUnitDetail)
def get_stock_unit(
    unit_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.get_stock_unit(db, unit_id)


@router.get("/routings", response_model=CCRoutingListResponse)
def list_routings(
    wo_number: Optional[str] = Query(None, max_length=100),
    status: Optional[Literal["DRAFT", "ACTIVE", "SUPERSEDED"]] = Query(None),
    material_source: Optional[Literal["CONTINUOUS_CASTING", "F1_PRODUCTION"]] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.list_routings(
        db, wo_number=wo_number, status_filter=status, material_source=material_source, limit=limit, offset=offset)


@router.get("/routings/{routing_id}", response_model=CCRoutingDetail)
def get_routing(
    routing_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.get_routing(db, routing_id)


@router.get("/allocations", response_model=CCAllocationListResponse)
def list_allocations(
    routing_id: Optional[uuid.UUID] = Query(None),
    wo_number: Optional[str] = Query(None, max_length=100),
    stock_unit_id: Optional[uuid.UUID] = Query(None),
    inward_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None, max_length=40),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.list_allocations(
        db, routing_id=routing_id, wo_number=wo_number, stock_unit_id=stock_unit_id, inward_id=inward_id,
        status_filter=status, limit=limit, offset=offset)


@router.get("/ledger", response_model=CCLedgerListResponse)
def list_ledger(
    stock_unit_id: Optional[uuid.UUID] = Query(None),
    inward_id: Optional[uuid.UUID] = Query(None),
    allocation_id: Optional[uuid.UUID] = Query(None),
    wo_number: Optional[str] = Query(None, max_length=100),
    routing_id: Optional[uuid.UUID] = Query(None),
    movement_type: Optional[MovementType] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.list_ledger(
        db, stock_unit_id=stock_unit_id, inward_id=inward_id, allocation_id=allocation_id, wo_number=wo_number,
        routing_id=routing_id, movement_type=movement_type, created_from=created_from, created_to=created_to,
        limit=limit, offset=offset)


@router.get("/cut-results", response_model=CCCutResultListResponse)
def list_cut_results(
    wo_number: Optional[str] = Query(None, max_length=100),
    routing_id: Optional[uuid.UUID] = Query(None),
    allocation_id: Optional[uuid.UUID] = Query(None),
    stock_unit_id: Optional[uuid.UUID] = Query(None),
    ledger_transaction_number: Optional[str] = Query(None, max_length=100),
    reconciliation_status: Optional[Literal["PENDING", "RECONCILED", "VARIANCE"]] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.list_cut_results(
        db, wo_number=wo_number, routing_id=routing_id, allocation_id=allocation_id, stock_unit_id=stock_unit_id,
        ledger_transaction_number=ledger_transaction_number, reconciliation_status=reconciliation_status,
        limit=limit, offset=offset)


# declared BEFORE /cut-results/{cut_result_id}, so "available" is never read as an id
@router.get("/cut-results/available", response_model=CCCutAvailableListResponse)
def list_available_cut_consumes(
    routing_id: Optional[uuid.UUID] = Query(None),
    wo_number: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.list_available_cut_consumes(
        db, routing_id=routing_id, wo_number=wo_number, limit=limit, offset=offset)


@router.get("/cut-results/{cut_result_id}", response_model=CCCutResultOut)
def get_cut_result(
    cut_result_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.get_cut_result(db, cut_result_id)


@router.get("/traceability/inwards/{inward_id}", response_model=CCTraceInward)
def trace_inward(
    inward_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.trace_inward(db, inward_id)


@router.get("/traceability/work-orders/{wo_number}", response_model=CCTraceWorkOrder)
def trace_work_order(
    wo_number: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.trace_work_order(db, wo_number)


@router.get("/work-orders/{wo_number}/gate-status", response_model=CCGateStatus)
def get_gate_status(
    wo_number: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ContinuousCastingReadService.get_gate_status(db, wo_number)
