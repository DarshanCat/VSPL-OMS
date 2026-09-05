from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.work_order import WorkOrder, WOStatus
from app.models.packing import PackingRecord
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.packing import PackingQueueItem, PackingUpdateRequest, PackingUpdateResponse

class PackingService:
    @staticmethod
    def get_packing_queue(db: Session) -> List[PackingQueueItem]:
        records = db.query(PackingRecord).join(WorkOrder).all()
        results = []
        for r in records:
            wo = r.work_order
            order = wo.order if wo else None
            customer_name = order.customer.name if (order and order.customer) else "VSPL Internal"
            part_number = order.part.part_number if (order and order.part) else "N/A"
            part_name = order.part.description if (order and order.part) else None
            grade = order.part.grade if (order and order.part) else None
            order_qty = wo.physical_wo_qty if wo else 0
            oar_number = order.oar_number if order else None

            results.append(PackingQueueItem(
                id=str(r.id),
                work_order_id=str(wo.id),
                wo_number=wo.wo_number,
                oar_number=oar_number,
                customer_name=customer_name,
                part_number=part_number,
                part_name=part_name,
                grade=grade,
                order_qty=order_qty,
                fi_approved_qty=r.fi_approved_qty,
                available_for_packing=r.available_for_packing,
                received_qty=r.received_qty,
                packed_qty=r.packed_qty,
                pending_qty=r.pending_qty,
                ready_for_dispatch_qty=r.ready_for_dispatch_qty,
                dispatched_qty=r.dispatched_qty,
                status=r.status,
                updated_at=r.updated_at or r.created_at or datetime.now()
            ))
        return results

    @staticmethod
    def update_packing(db: Session, req: PackingUpdateRequest, current_user: Optional[User] = None) -> PackingUpdateResponse:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.wo_number.strip()).first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{req.wo_number}' not found."
            )

        packing_rec = db.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
        if not packing_rec:
            packing_rec = PackingRecord(
                work_order_id=wo.id,
                fi_approved_qty=wo.physical_wo_qty,
                available_for_packing=wo.physical_wo_qty,
                received_qty=wo.physical_wo_qty,
                packed_qty=0,
                pending_qty=wo.physical_wo_qty,
                ready_for_dispatch_qty=0,
                status="In-Packing"
            )
            db.add(packing_rec)
            db.flush()

        if req.packed_quantity > packing_rec.pending_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot pack {req.packed_quantity} pieces. Only {packing_rec.pending_qty} pieces are pending packing for {req.wo_number} (Approved: {packing_rec.fi_approved_qty}, Packed: {packing_rec.packed_qty})."
            )

        # Update packing quantities
        packing_rec.packed_qty += req.packed_quantity
        packing_rec.pending_qty -= req.packed_quantity
        packing_rec.ready_for_dispatch_qty += req.packed_quantity

        if packing_rec.pending_qty == 0:
            packing_rec.status = "Ready-for-Dispatch"
            wo.status = WOStatus.READY
        else:
            packing_rec.status = "In-Packing"

        # Create audit log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Packing Operator",
            action="PACKING_UPDATE",
            entity="PackingRecord",
            entity_id=wo.wo_number,
            old_value=f"Pending: {packing_rec.pending_qty + req.packed_quantity}, Ready: {packing_rec.ready_for_dispatch_qty - req.packed_quantity}",
            new_value=f"Packed: {req.packed_quantity}, Total Packed: {packing_rec.packed_qty}, Ready: {packing_rec.ready_for_dispatch_qty}",
            details=f"Box count: {req.box_count}, Type: {req.package_type}. {req.remarks or ''}"
        )
        db.add(audit)

        db.commit()
        db.refresh(packing_rec)

        return PackingUpdateResponse(
            success=True,
            wo_number=wo.wo_number,
            packed_this_batch=req.packed_quantity,
            total_packed=packing_rec.packed_qty,
            remaining_pending=packing_rec.pending_qty,
            ready_for_dispatch=packing_rec.ready_for_dispatch_qty,
            message=f"Successfully packed {req.packed_quantity} pieces for {wo.wo_number}. Ready for dispatch: {packing_rec.ready_for_dispatch_qty}."
        )
