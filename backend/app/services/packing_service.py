from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.work_order import WorkOrder, WOStatus
from app.models.production_movement import StageWIP
from app.models.packing import PackingRecord, PackingTransaction
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
        # 1. Idempotency Check: Prevent duplicate submissions on double-click / network retry
        if req.client_request_id:
            existing_txn = db.query(PackingTransaction).filter(
                PackingTransaction.client_request_id == req.client_request_id.strip()
            ).first()
            if existing_txn:
                wo_existing = db.query(WorkOrder).filter(WorkOrder.id == existing_txn.work_order_id).first()
                pr_existing = db.query(PackingRecord).filter(PackingRecord.work_order_id == existing_txn.work_order_id).first()
                return PackingUpdateResponse(
                    success=True,
                    wo_number=wo_existing.wo_number if wo_existing else req.wo_number,
                    client_request_id=existing_txn.client_request_id,
                    packed_this_batch=existing_txn.packed_quantity,
                    total_packed=pr_existing.packed_qty if pr_existing else existing_txn.packed_quantity,
                    remaining_pending=pr_existing.pending_qty if pr_existing else 0,
                    ready_for_dispatch=pr_existing.ready_for_dispatch_qty if pr_existing else 0,
                    message=f"Duplicate request detected with token '{req.client_request_id}'. Returning original transaction."
                )

        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.wo_number.strip()).with_for_update().first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{req.wo_number}' not found."
            )

        packing_rec = db.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).with_for_update().first()
        if not packing_rec:
            # Check PACKING or FI StageWIP to see how many parts actually arrived
            pack_wip = db.query(StageWIP).filter(
                StageWIP.work_order_id == wo.id,
                StageWIP.stage.in_(["PACKING", "PACKING / BSR", "PACKING/BSR"])
            ).first()
            fi_wip = db.query(StageWIP).filter(
                StageWIP.work_order_id == wo.id,
                StageWIP.stage.in_(["FI", "FINAL INSPECTION", "FINAL_INSPECTION"])
            ).first()

            if pack_wip and (pack_wip.ent_qty > 0 or pack_wip.available_wip > 0):
                actual_available = max(pack_wip.ent_qty, pack_wip.available_wip)
            elif fi_wip and fi_wip.ok_qty > 0:
                actual_available = fi_wip.ok_qty
            else:
                total_rejections = sum(w.rejected_qty for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all())
                actual_available = max(0, (wo.physical_wo_qty or 0) - total_rejections)

            packing_rec = PackingRecord(
                work_order_id=wo.id,
                fi_approved_qty=actual_available,
                available_for_packing=actual_available,
                received_qty=actual_available,
                packed_qty=0,
                pending_qty=actual_available,
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

        # Record immutable packing transaction ledger entry
        txn = PackingTransaction(
            work_order_id=wo.id,
            client_request_id=req.client_request_id.strip() if req.client_request_id else None,
            packed_quantity=req.packed_quantity,
            box_count=req.box_count,
            package_type=req.package_type,
            remarks=req.remarks,
            created_by=current_user.id if current_user else None
        )
        db.add(txn)

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

        try:
            db.commit()
        except IntegrityError:
            # A concurrent request with the same idempotency key won the race.
            db.rollback()
            existing_txn = db.query(PackingTransaction).filter(
                PackingTransaction.client_request_id == req.client_request_id.strip()
            ).first()
            if not existing_txn:
                raise
            wo_existing = db.query(WorkOrder).filter(WorkOrder.id == existing_txn.work_order_id).first()
            pr_existing = db.query(PackingRecord).filter(PackingRecord.work_order_id == existing_txn.work_order_id).first()
            return PackingUpdateResponse(
                success=True,
                wo_number=wo_existing.wo_number if wo_existing else req.wo_number,
                client_request_id=existing_txn.client_request_id,
                packed_this_batch=existing_txn.packed_quantity,
                total_packed=pr_existing.packed_qty if pr_existing else existing_txn.packed_quantity,
                remaining_pending=pr_existing.pending_qty if pr_existing else 0,
                ready_for_dispatch=pr_existing.ready_for_dispatch_qty if pr_existing else 0,
                message=f"Duplicate request detected with token '{req.client_request_id}'. Returning original transaction."
            )
        db.refresh(packing_rec)

        return PackingUpdateResponse(
            success=True,
            wo_number=wo.wo_number,
            client_request_id=req.client_request_id,
            packed_this_batch=req.packed_quantity,
            total_packed=packing_rec.packed_qty,
            remaining_pending=packing_rec.pending_qty,
            ready_for_dispatch=packing_rec.ready_for_dispatch_qty,
            message=f"Successfully packed {req.packed_quantity} pieces for {wo.wo_number}. Ready for dispatch: {packing_rec.ready_for_dispatch_qty}."
        )
