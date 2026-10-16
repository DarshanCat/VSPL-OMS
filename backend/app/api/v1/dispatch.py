from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.core.roles import DISPATCH_EXECUTION_ROLES, PLANNING_ROLES
from app.models.user import User
from app.schemas.dispatch import (
    DispatchQueueItem, DispatchRequest, DispatchResponse, DispatchHistoryItem,
    InvoicePaymentUpdate, CustomerReturnCreate, CustomerReturnOut, CustomerReturnResponse
)
from app.services.dispatch_service import DispatchService

router = APIRouter(prefix="/api/v1/dispatch", tags=["dispatch"])

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
    user: User = Depends(require_roles(*DISPATCH_EXECUTION_ROLES))
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
    """Retrieve immutable dispatch transaction history with invoice payment details."""
    return DispatchService.get_dispatch_history(db, limit=limit, offset=offset)

@router.patch("/{dispatch_id}/payment", response_model=DispatchHistoryItem)
def update_invoice_payment(
    dispatch_id: str = Path(..., description="Dispatch ID or Invoice Number"),
    payload: InvoicePaymentUpdate = ...,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Update payment status (PAID, UNPAID, PARTIALLY_PAID) and transaction reference for an invoice."""
    return DispatchService.update_invoice_payment(db, dispatch_id, payload, current_user=user)

@router.get("/pricing-lookup")
def lookup_product_pricing(
    customer_code: Optional[str] = Query(None),
    part_number: Optional[str] = Query(None),
    wo_number: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Lookup product selling price per piece from PO Line / PO Master."""
    return DispatchService.lookup_product_pricing(
        db, customer_code=customer_code, part_number=part_number, wo_number=wo_number
    )

@router.post("/returns", response_model=CustomerReturnResponse)
def create_customer_return(
    payload: CustomerReturnCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Record customer complaint & sales return and send directly to conversion as a new Work Order ID."""
    return DispatchService.create_customer_return(db, payload, current_user=user)

@router.get("/returns", response_model=List[CustomerReturnOut])
def list_customer_returns(
    customer_code: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve all customer return records with linked conversion Work Order IDs and product values."""
    return DispatchService.list_customer_returns(
        db, customer_code=customer_code, search=search, limit=limit, offset=offset
    )
