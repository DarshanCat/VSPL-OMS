from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.work_order import (
    WorkOrderListItem, WorkOrderTrackingDetail, WorkOrderRouteResponse,
    PlanningSummaryResponse, MovableWorkOrderItem
)
from app.services.work_order_service import WorkOrderService

router = APIRouter(prefix="/api/v1/work-orders", tags=["work-orders"])

@router.get("/movable", response_model=List[MovableWorkOrderItem])
def list_movable_work_orders(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve all work orders that have produced parts / WIP waiting at a stage
    to be moved to the next sequential stage, sorted priority-wise."""
    return WorkOrderService.list_movable_work_orders(db, limit=limit)

@router.get("/planning-summary", response_model=PlanningSummaryResponse)
def get_planning_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve live aggregate planning metrics for production planners:
    unreleased count, released count, producing today count, ready for production count, etc."""
    return WorkOrderService.get_planning_summary(db)

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
    route_data = WorkOrderService.get_work_order_route(db, wo_identifier)
    if not route_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{wo_identifier}' not found."
        )
    return route_data

@router.get("/{wo_identifier}/stage/{stage_name}/state")
def get_stage_state(
    wo_identifier: str,
    stage_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve authoritative live stage state (Target, OK, Rej, InProc, OnHand, Avail WIP, RAG)."""
    state_data = WorkOrderService.get_stage_state(db, wo_identifier, stage_name)
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Order '{wo_identifier}' or Stage '{stage_name}' not found."
        )
    return state_data
