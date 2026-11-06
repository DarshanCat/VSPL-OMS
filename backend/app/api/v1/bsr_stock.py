from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.bsr_stock_service import BSRStockService

router = APIRouter(prefix="/api/v1/bsr-stock", tags=["bsr-stock"])


class AllocateStockRequest(BaseModel):
    oar_id: str = Field(..., description="OAR (Order) UUID")
    quantity: int = Field(..., gt=0, description="Quantity to allocate from finished BSR stock")


class DepositStockRequest(BaseModel):
    part_id: str
    quantity: int = Field(..., gt=0)
    source_wo_id: Optional[str] = None
    heat_number: Optional[str] = None
    remarks: Optional[str] = None


@router.get("", response_model=List[dict])
def list_bsr_stock(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all available Finished Goods Buffer Stock in BSR grouped by part."""
    return BSRStockService.list_all_stock(db)


@router.get("/part/{part_id}", response_model=dict)
def get_stock_for_part(
    part_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get available BSR finished stock for a specific part."""
    return BSRStockService.get_stock_for_part(db, part_id)


@router.post("/allocate", response_model=dict)
def allocate_stock_to_oar(
    req: AllocateStockRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Allocate finished BSR buffer stock to satisfy an OAR without releasing new casting WOs."""
    return BSRStockService.allocate_to_oar(db, req.oar_id, req.quantity, current_user=user)


@router.post("/deposit", response_model=dict)
def deposit_excess_stock(
    req: DepositStockRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Deposit excess finished goods into BSR stock."""
    import uuid
    stock = BSRStockService.deposit_excess(
        db=db,
        part_id=uuid.UUID(req.part_id),
        qty=req.quantity,
        source_wo_id=uuid.UUID(req.source_wo_id) if req.source_wo_id else None,
        heat_number=req.heat_number,
        remarks=req.remarks,
        actor_name=user.full_name or "Operator"
    )
    return {
        "success": True,
        "stock_id": str(stock.id),
        "available_qty": stock.available_qty,
        "message": f"Successfully deposited {stock.available_qty} pcs into BSR stock."
    }
