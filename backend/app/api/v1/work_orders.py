from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.work_order import WorkOrderListItem, WorkOrderTrackingDetail
from app.services.work_order_service import WorkOrderService

router = APIRouter(prefix="/api/v1/work-orders", tags=["work-orders"])

@router.get("", response_model=List[WorkOrderListItem])
def list_work_orders(
    search: Optional[str] = Query(None, description="Search by WO, Customer, Part, or PO"),
    stage: Optional[str] = Query(None, description="Filter by current stage"),
    customer_code: Optional[str] = Query(None, description="Filter by customer code"),
    status_filter: Optional[str] = Query(None, description="Filter by WO status"),
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
