import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.bsr_stock import BSRStock
from app.models.order import Order
from app.models.work_order import WorkOrder
from app.models.order import Part
from app.models.audit import AuditLog
from app.models.user import User


class BSRStockService:
    @staticmethod
    def get_stock_for_part(db: Session, part_id: str) -> dict:
        part_uuid = uuid.UUID(str(part_id))
        records = db.query(BSRStock).filter(
            BSRStock.part_id == part_uuid,
            BSRStock.available_qty > 0
        ).order_by(BSRStock.created_at.asc()).all()

        total_available = sum(r.available_qty for r in records)
        total_allocated = db.query(func.coalesce(func.sum(BSRStock.allocated_qty), 0)).filter(
            BSRStock.part_id == part_uuid
        ).scalar() or 0

        lots = [
            {
                "id": str(r.id),
                "source_wo_number": r.source_wo.wo_number if r.source_wo else "N/A",
                "heat_number": r.heat_number,
                "available_qty": r.available_qty,
                "allocated_qty": r.allocated_qty,
                "created_at": r.created_at
            }
            for r in records
        ]

        part = db.query(Part).filter(Part.id == part_uuid).first()

        return {
            "part_id": str(part_id),
            "part_number": part.part_number if part else "N/A",
            "part_description": part.description if part else None,
            "total_available": total_available,
            "total_allocated": total_allocated,
            "lots": lots
        }

    @staticmethod
    def list_all_stock(db: Session) -> List[dict]:
        parts = db.query(Part).all()
        results = []
        for p in parts:
            stock = BSRStockService.get_stock_for_part(db, str(p.id))
            if stock["total_available"] > 0 or stock["total_allocated"] > 0:
                results.append(stock)
        return results

    @staticmethod
    def deposit_excess(
        db: Session,
        part_id: uuid.UUID,
        qty: int,
        source_wo_id: Optional[uuid.UUID] = None,
        heat_number: Optional[str] = None,
        remarks: Optional[str] = None,
        actor_name: str = "System"
    ) -> BSRStock:
        if qty <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Deposit quantity must be greater than zero.")

        stock = BSRStock(
            part_id=part_id,
            available_qty=qty,
            allocated_qty=0,
            source_wo_id=source_wo_id,
            heat_number=heat_number,
            remarks=remarks
        )
        db.add(stock)
        db.flush()

        db.add(AuditLog(
            user_name=actor_name,
            action="BSR_EXCESS_STOCK_DEPOSITED",
            entity="BSRStock",
            entity_id=str(stock.id),
            details=f"Deposited {qty} pcs into BSR stock from WO {source_wo_id or 'Manual'} (Heat: {heat_number or 'N/A'})"
        ))
        db.commit()
        db.refresh(stock)
        return stock

    @staticmethod
    def allocate_to_oar(
        db: Session,
        oar_id: str,
        qty: int,
        current_user: Optional[User] = None
    ) -> dict:
        if qty <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Allocation quantity must be greater than zero.")

        order = db.query(Order).filter(Order.id == uuid.UUID(str(oar_id))).first()
        if not order:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"OAR with id '{oar_id}' not found.")

        # Check total remaining unallocated OAR balance
        current_stock_fulfilled = getattr(order, "fulfilled_from_stock_qty", 0) or 0
        wos_allocated = sum(wo.physical_wo_qty for wo in order.work_orders)
        remaining_oar_need = max(order.po_qty - (wos_allocated + current_stock_fulfilled), 0)

        if qty > remaining_oar_need:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Cannot allocate {qty} pcs from stock. Remaining unallocated demand on OAR {order.oar_number} is only {remaining_oar_need} pcs."
            )

        # Check available BSR stock for this part
        lots = db.query(BSRStock).filter(
            BSRStock.part_id == order.part_id,
            BSRStock.available_qty > 0
        ).order_by(BSRStock.created_at.asc()).with_for_update().all()

        total_avail = sum(lot.available_qty for lot in lots)
        if qty > total_avail:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Insufficient BSR stock available. Requested {qty} pcs, but only {total_avail} pcs available in BSR."
            )

        # FIFO allocation across lots
        needed = qty
        for lot in lots:
            take = min(lot.available_qty, needed)
            lot.available_qty -= take
            lot.allocated_qty += take
            needed -= take
            if needed == 0:
                break

        order.fulfilled_from_stock_qty = current_stock_fulfilled + qty

        actor = current_user.full_name if current_user else "Planner"
        db.add(AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=actor,
            action="BSR_STOCK_ALLOCATED_TO_OAR",
            entity="Order",
            entity_id=order.oar_number or str(order.id),
            details=f"Allocated {qty} pcs from BSR finished stock to fulfill OAR {order.oar_number} directly."
        ))

        db.commit()
        db.refresh(order)

        new_stock_fulfilled = order.fulfilled_from_stock_qty
        new_remaining = max(order.po_qty - (wos_allocated + new_stock_fulfilled), 0)

        return {
            "success": True,
            "oar_number": order.oar_number,
            "allocated_from_stock": qty,
            "total_fulfilled_from_stock": new_stock_fulfilled,
            "remaining_to_plan": new_remaining,
            "message": f"Successfully allocated {qty} pcs from BSR finished stock to OAR {order.oar_number}. Remaining quantity to produce: {new_remaining} pcs."
        }
