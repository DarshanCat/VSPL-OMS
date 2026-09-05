from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.dispatch import DispatchQueueItem, DispatchRequest, DispatchResponse, DispatchHistoryItem
from app.services.oms_integration_service import OMSIntegrationService

class DispatchService:
    @staticmethod
    def get_dispatch_queue(db: Session) -> List[DispatchQueueItem]:
        packing_records = db.query(PackingRecord).join(WorkOrder).filter(PackingRecord.ready_for_dispatch_qty > 0).all()
        results = []
        for pr in packing_records:
            wo = pr.work_order
            order = wo.order if wo else None
            customer_code = order.customer.customer_code if (order and order.customer) else "CUST-001"
            customer_name = order.customer.name if (order and order.customer) else "VSPL Customer"
            customer_po = order.customer_po if order else "PO-GEN"
            part_number = order.part.part_number if (order and order.part) else "N/A"
            part_name = order.part.description if (order and order.part) else None
            order_qty = wo.physical_wo_qty if wo else 0
            oar_number = order.oar_number if order else None

            results.append(DispatchQueueItem(
                id=str(pr.id),
                work_order_id=str(wo.id),
                wo_number=wo.wo_number,
                oar_number=oar_number,
                customer_code=customer_code,
                customer_name=customer_name,
                customer_po=customer_po,
                part_number=part_number,
                part_name=part_name,
                order_qty=order_qty,
                packed_completed_qty=pr.packed_qty,
                ready_for_dispatch_qty=pr.ready_for_dispatch_qty,
                already_dispatched_qty=pr.dispatched_qty,
                status=pr.status
            ))
        return results

    @staticmethod
    def execute_dispatch(db: Session, req: DispatchRequest, current_user: Optional[User] = None) -> DispatchResponse:
        # Atomic lock on Work Order and Packing Record
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.wo_number.strip()).with_for_update().first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{req.wo_number}' not found."
            )

        packing_rec = db.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).with_for_update().first()
        ready_qty = packing_rec.ready_for_dispatch_qty if packing_rec else 0

        # CRITICAL DISPATCH GATEKEEPER VALIDATION
        if req.dispatched_quantity > ready_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot dispatch {req.dispatched_quantity} pieces. Only {ready_qty} pieces are ready for dispatch after Packing / BSR for WO '{req.wo_number}'."
            )

        # Update packing record
        packing_rec.ready_for_dispatch_qty -= req.dispatched_quantity
        packing_rec.dispatched_qty += req.dispatched_quantity

        if packing_rec.ready_for_dispatch_qty == 0 and packing_rec.pending_qty == 0:
            packing_rec.status = "Fully-Dispatched"
            wo.status = WOStatus.DISPATCHED
            wo.current_stage = "Completed"
        else:
            packing_rec.status = "Partially-Dispatched"

        # Update StageWIP at Packing/BSR/Dispatch to reflect parts cleared and shipped
        wips = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
        for w in wips:
            if w.stage.upper() in ("PACKING / BSR", "PACKING/BSR", "PACKING", "BSR", "DISPATCH"):
                w.ok_qty += req.dispatched_quantity
                w.moved_out_qty += req.dispatched_quantity

        # Record in Dispatch table
        order = wo.order
        customer_po = req.customer_po or (order.customer_po if order else "N/A")
        now = datetime.now()

        dispatch_entry = Dispatch(
            work_order_id=wo.id,
            customer_po=customer_po,
            invoice_number=req.invoice_number.strip(),
            dispatched_qty=req.dispatched_quantity,
            dispatch_date=now,
            created_by=current_user.id if current_user else None
        )
        db.add(dispatch_entry)

        # Recompute OMS Authoritative State
        OMSIntegrationService.recompute_work_order(db, wo)

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Dispatch Officer",
            action="DISPATCH_GOODS",
            entity="Dispatch",
            entity_id=req.invoice_number,
            old_value=f"Ready for Dispatch: {ready_qty}",
            new_value=f"Dispatched: {req.dispatched_quantity}, Remaining Ready: {packing_rec.ready_for_dispatch_qty}",
            details=f"WO: {wo.wo_number}, Invoice: {req.invoice_number}, Vehicle: {req.vehicle_number or 'N/A'}, Transporter: {req.transporter or 'N/A'}"
        )
        db.add(audit)

        db.commit()
        db.refresh(packing_rec)
        db.refresh(wo)

        return DispatchResponse(
            success=True,
            invoice_number=req.invoice_number,
            wo_number=wo.wo_number,
            dispatched_quantity=req.dispatched_quantity,
            remaining_ready_for_dispatch=packing_rec.ready_for_dispatch_qty,
            wo_status=wo.status.value,
            message=f"Successfully dispatched {req.dispatched_quantity} pieces under Invoice '{req.invoice_number}'. Remaining ready: {packing_rec.ready_for_dispatch_qty}."
        )

    @staticmethod
    def get_dispatch_history(db: Session) -> List[DispatchHistoryItem]:
        records = db.query(Dispatch).join(WorkOrder).order_by(Dispatch.dispatch_date.desc()).all()
        results = []
        for d in records:
            wo = d.work_order
            order = wo.order if wo else None
            cust_name = order.customer.name if (order and order.customer) else "VSPL Customer"
            part_no = order.part.part_number if (order and order.part) else "N/A"
            dispatcher = d.dispatcher.full_name if d.dispatcher else "Dispatch Dept"

            results.append(DispatchHistoryItem(
                id=str(d.id),
                work_order_id=str(wo.id),
                wo_number=wo.wo_number,
                customer_name=cust_name,
                customer_po=d.customer_po or (order.customer_po if order else ""),
                part_number=part_no,
                invoice_number=d.invoice_number or "N/A",
                dispatched_qty=d.dispatched_qty,
                dispatch_date=d.dispatch_date or datetime.now(),
                dispatcher_name=dispatcher
            ))
        return results
