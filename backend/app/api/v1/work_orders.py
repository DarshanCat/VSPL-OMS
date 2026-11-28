from app.core.gate_scope import deny_if_supervisor, filter_to_gate, require_own_stage, require_wo_at_gate, supervisor_gate, wo_ids_at_gate
from datetime import date, datetime
from pydantic import BaseModel, Field
from app.core.departments import STAGE_OF_ROLE, normalize_stage
from app.core.roles import PLANNING_ROLES, STAGE_MANAGER_ROLES, WO_GENERATION_ROLES
from app.models.audit import AuditLog
from app.models.work_order import WorkOrder, WORoute
from app.services.work_queue_service import WorkQueueService
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import UserRole
from app.core.roles import PLANNING_ROLES
from app.schemas.operations import WorkOrderCreatePayload, WorkOrderCreateResponse
from app.services.operations_service import OperationsService
from app.models.user import User
from app.schemas.work_order import (
    WorkOrderListItem, WorkOrderTrackingDetail, WorkOrderRouteResponse,
    PlanningSummaryResponse, MovableWorkOrderItem
)
from app.services.work_order_service import WorkOrderService

router = APIRouter(prefix="/api/v1/work-orders", tags=["work-orders"])

class StagePlanItem(BaseModel):
    stage: str = Field(..., min_length=1, max_length=40)
    planned_start: Optional[date] = None
    planned_end: Optional[date] = None


class StagePlanUpdate(BaseModel):
    stages: List[StagePlanItem] = Field(..., min_length=1, max_length=50)
    reason: str = Field(..., min_length=3, max_length=500)


@router.get("/queue")
def get_stage_work_queue(
    stage: str = Query(..., min_length=1, max_length=40, description="Stage, e.g. F1, F2, F3, SP, FI, PACKING"),
    days: int = Query(2, ge=0, le=14, description="How many days ahead counts as 'next'"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Read-only shop-floor queue: WOs with material at `stage`, bucketed by that stage's
    planned due date (overdue / today / next N days / later / no date)."""
    require_own_stage(user, stage)
    return WorkQueueService.get_stage_queue(db, stage=stage, days=days)


@router.patch("/{wo_identifier}/stage-plan")
def update_stage_plan(
    wo_identifier: str,
    payload: StagePlanUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*(PLANNING_ROLES + STAGE_MANAGER_ROLES))),
):
    """Change planned start/end dates of route stages (planning only). PPC may change any
    stage; a stage Manager only their own stage. Audit-logged with the reason."""
    wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_identifier.strip()).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Work Order '{wo_identifier}' not found.")
    status_value = getattr(wo.status, "value", wo.status)
    if status_value in ("dispatched", "closed"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Work Order '{wo.wo_number}' is {status_value}.")
    if not user.has_any_role(*PLANNING_ROLES):
        own = STAGE_OF_ROLE.get(user.role)
        if any(normalize_stage(p.stage) != own for p in payload.stages):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You can only change plan dates for your own stage ({own}).",
            )
    routes = {r.stage.strip().upper(): r for r in db.query(WORoute).filter(WORoute.work_order_id == wo.id).all()}
    changes = []
    for item in payload.stages:
        row = routes.get(item.stage.strip().upper())
        if row is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Stage '{item.stage}' is not on this Work Order's route.")
        start = item.planned_start if item.planned_start is not None else row.planned_start
        end = item.planned_end if item.planned_end is not None else row.planned_end
        if start and end and start > end:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Stage '{row.stage}': planned start cannot be after planned end.")
        if (start, end) != (row.planned_start, row.planned_end):
            changes.append(f"{row.stage} plan {row.planned_start}..{row.planned_end} -> {start}..{end}")
            row.planned_start, row.planned_end = start, end
            row.plan_source = "MANUAL"
            row.plan_updated_at = datetime.now()
    if changes:
        wo.plan_version = (wo.plan_version or 0) + 1   # an older Excel plan is now stale
        db.add(AuditLog(user_id=user.id, user_name=user.full_name, action="WO_STAGE_PLAN_EDITED",
                        entity="WorkOrder", entity_id=wo.wo_number, new_value="; ".join(changes)[:2000], details=payload.reason))
        db.commit()
    return {
        "wo_number": wo.wo_number,
        "changes": changes,
        "stage_plans": {
            r.stage: {"planned_start": r.planned_start.isoformat() if r.planned_start else None,
                      "planned_end": r.planned_end.isoformat() if r.planned_end else None}
            for r in sorted(routes.values(), key=lambda r: r.sequence)
        },
    }


@router.get("/movable", response_model=List[MovableWorkOrderItem])
def list_movable_work_orders(
    limit: int = Query(50, ge=1, le=200),
    stage: Optional[str] = Query(None, description="Filter movable work orders by origin stage e.g. F1, F2, F3..."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve all work orders that have produced parts / WIP waiting at a stage
    to be moved to the next sequential stage, sorted priority-wise."""
    gate = supervisor_gate(user)
    if gate:
        stage = gate  # gate supervisors only see their own gate's movable WOs
    return WorkOrderService.list_movable_work_orders(db, limit=limit, stage_filter=stage)

@router.get("/planning-summary", response_model=PlanningSummaryResponse)
def get_planning_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve live aggregate planning metrics for production planners:
    unreleased count, released count, producing today count, ready for production count, etc."""
    deny_if_supervisor(user)
    return WorkOrderService.get_planning_summary(db)

@router.post("", response_model=WorkOrderCreateResponse)
def create_work_order(
    payload: WorkOrderCreatePayload,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WO_GENERATION_ROLES))
):
    """Step 2: Planner generates Work Order(s) from a created OAR."""
    return OperationsService.create_work_order(db, payload, current_user=user)

@router.get("", response_model=List[WorkOrderListItem])
def list_work_orders(
    search: Optional[str] = Query(None, description="Search by WO, Customer, Part, or PO"),
    stage: Optional[str] = Query(None, description="Filter by current stage"),
    customer_code: Optional[str] = Query(None, description="Filter by customer code"),
    status_filter: Optional[str] = Query(None, description="Filter by WO status"),
    casting_process: Optional[str] = Query(
        None, description="Filter by casting process / route, e.g. 'CONTINUOUS' for Continuous Casting-eligible WOs"),
    release_filter: Optional[str] = Query(
        None, description="Filter by release status: 'all', 'released', 'unreleased', 'ready_for_production'"),
    sort_by: Optional[str] = Query(
        None, description="Sort order: 'wo_date_desc', 'wo_date_asc', 'release_date_desc', 'release_date_asc', 'delivery_date_asc', 'delivery_date_desc', 'wo_number_asc', 'wo_number_desc'"),
    exclude_dispatched: bool = Query(
        False, description="Exclude completely dispatched and closed work orders"),
    from_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    date_type: Optional[str] = Query("wo_date", description="Date field to filter: 'wo_date', 'release_date', 'delivery_date'"),
    classification: Optional[str] = Query(None, description="Filter by classification: 'Production' or 'NPD'"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List work orders with live stage progress, available WIP, and delivery risk ratings."""
    gate = supervisor_gate(user)
    if gate:
        # Gate supervisors: only WOs with material at their gate. Same query, then
        # filtered and paged here, so nothing changes for any other caller.
        full = WorkOrderService.list_work_orders(
            db, search=search, stage=stage, customer_code=customer_code, status_filter=status_filter,
            casting_process=casting_process, release_filter=release_filter, sort_by=sort_by,
            exclude_dispatched=exclude_dispatched, from_date=from_date, to_date=to_date,
            date_type=date_type, classification=classification, limit=500, offset=0,
        )
        return filter_to_gate(full, wo_ids_at_gate(db, gate))[offset:offset + limit]
    return WorkOrderService.list_work_orders(
        db,
        search=search,
        stage=stage,
        customer_code=customer_code,
        status_filter=status_filter,
        casting_process=casting_process,
        release_filter=release_filter,
        sort_by=sort_by,
        exclude_dispatched=exclude_dispatched,
        from_date=from_date,
        to_date=to_date,
        date_type=date_type,
        classification=classification,
        limit=limit,
        offset=offset
    )

@router.get("/{wo_identifier}/tracking", response_model=WorkOrderTrackingDetail)
def get_work_order_tracking(
    wo_identifier: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve full interactive tracking detail with stage pipeline timeline, WIP, and RAG status."""
    require_wo_at_gate(db, user, wo_identifier)
    detail = WorkOrderService.get_tracking_detail(db, wo_identifier)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{wo_identifier}' not found."
        )
    return detail

@router.get("/{wo_identifier}/route", response_model=WorkOrderRouteResponse)
def get_work_order_route(
    wo_identifier: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve the actual dynamic route, targets, and next stage for this Work Order."""
    require_wo_at_gate(db, user, wo_identifier)
    route_data = WorkOrderService.get_work_order_route(db, wo_identifier)
    if not route_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{wo_identifier}' not found."
        )
    return route_data

# Who may open the route card (CEO counts as Admin). Stage managers see every stage; gate supervisors are
# not listed because they have no planning menu.
ROUTE_CARD_ROLES = (
    UserRole.ADMIN, UserRole.PLANNER, UserRole.PRODUCTION_MANAGER, UserRole.QA, UserRole.QUALITY, UserRole.SCM,
    UserRole.F1_MANAGER, UserRole.F2_MANAGER, UserRole.F3_MANAGER, UserRole.SP_MANAGER,
    UserRole.FI_MANAGER, UserRole.PACKING_MANAGER, UserRole.DISPATCH_MANAGER,
)


@router.get("/{wo_identifier}/route-card")
def get_work_order_route_card(
    wo_identifier: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ROUTE_CARD_ROLES))
):
    """Printable route card of a work order, drawn live from OMS data (read only, nothing stored)."""
    from app.core.config import settings as _settings
    if not _settings.ROUTE_CARD_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route card is not enabled")
    require_wo_at_gate(db, user, wo_identifier)
    from app.services.route_card_service import build_route_card
    card = build_route_card(db, wo_identifier)
    if not card:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{wo_identifier}' not found."
        )
    return card

@router.get("/{wo_identifier}/stage/{stage_name}/state")
def get_stage_state(
    wo_identifier: str,
    stage_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve authoritative live stage state (Target, OK, Rej, InProc, OnHand, Avail WIP, RAG)."""
    require_own_stage(user, stage_name)
    require_wo_at_gate(db, user, wo_identifier)
    state_data = WorkOrderService.get_stage_state(db, wo_identifier, stage_name)
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{wo_identifier}' or Stage '{stage_name}' not found."
        )
    return state_data

@router.delete("/{wo_identifier}")
def delete_work_order(
    wo_identifier: str,
    force_unstarted_release: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """Safely delete an unreleased Work Order (or ADMIN/PLANNER-forced unstarted released WO) with zero shop-floor/child activity."""
    if force_unstarted_release:
        from app.models.user import UserRole
        allowed_roles = {UserRole.ADMIN, UserRole.PLANNER, UserRole.PRODUCTION_MANAGER}
        has_permission = False
        if hasattr(user, "has_any_role") and user.has_any_role(*allowed_roles):
            has_permission = True
        elif user.role in allowed_roles:
            has_permission = True
        else:
            user_val = (user.role.value if hasattr(user.role, "value") else str(user.role)).lower()
            if user_val in {"admin", "planner", "production_manager"}:
                has_permission = True

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only ADMIN, PLANNER, or PRODUCTION_MANAGER can delete an unstarted released Work Order."
            )
    return OperationsService.delete_work_order(
        db, wo_identifier, current_user=user, force_unstarted_release=force_unstarted_release
    )
