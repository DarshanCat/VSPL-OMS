from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
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
        # 1. Idempotency Check: Prevent duplicate submissions on double-click / network retry
        if req.client_request_id:
            existing_dispatch = db.query(Dispatch).filter(
                Dispatch.client_request_id == req.client_request_id.strip()
            ).first()
            if existing_dispatch:
                wo_existing = db.query(WorkOrder).filter(WorkOrder.id == existing_dispatch.work_order_id).first()
                pr_existing = db.query(PackingRecord).filter(PackingRecord.work_order_id == existing_dispatch.work_order_id).first()
                return DispatchResponse(
                    success=True,
                    invoice_number=existing_dispatch.invoice_number or req.invoice_number,
                    wo_number=wo_existing.wo_number if wo_existing else req.wo_number,
                    client_request_id=existing_dispatch.client_request_id,
                    dispatched_quantity=existing_dispatch.dispatched_qty,
                    remaining_ready_for_dispatch=pr_existing.ready_for_dispatch_qty if pr_existing else 0,
                    wo_status=wo_existing.status.value if wo_existing else "unknown",
                    message=f"Duplicate request detected with token '{req.client_request_id}'. Returning original transaction."
                )

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

        # If this WO's route defines BSR as its own distinct stage (separate from PACKING),
        # the packing action alone does not clear material for dispatch — it must also have
        # actually been moved into BSR (the documented Packing -> BSR -> Dispatch flow).
        # `PackingRecord.ready_for_dispatch_qty` is credited as soon as packing is recorded
        # regardless of route, so routes with a separate BSR stage need this additional gate
        # against the quantity actually entered into the BSR stage (StageWIP.ent_qty), matching
        # the existing Packing->BSR movement semantics (no separate BSR "production entry" is
        # part of the documented flow).
        route_stage_names_upper = [
            r.stage.upper() for r in db.query(WORoute).filter(WORoute.work_order_id == wo.id).all()
        ]
        if "PACKING" in route_stage_names_upper and "BSR" in route_stage_names_upper:
            bsr_wip = db.query(StageWIP).filter(
                StageWIP.work_order_id == wo.id,
                StageWIP.stage == "BSR"
            ).first()
            bsr_entered_qty = bsr_wip.ent_qty if bsr_wip else 0
            already_dispatched = packing_rec.dispatched_qty
            if already_dispatched + req.dispatched_quantity > bsr_entered_qty:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot dispatch {req.dispatched_quantity} pieces for WO '{req.wo_number}': "
                        f"this route requires material to be moved into BSR before dispatch. Only "
                        f"{max(bsr_entered_qty - already_dispatched, 0)} pieces have entered BSR."
                    )
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

        # Update StageWIP only at the WO's actual terminal (DISPATCH) stage per its
        # persisted route, to avoid crediting the same dispatch quantity to multiple
        # StageWIP rows (e.g. when PACKING and BSR are separate stages in the route).
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        terminal_stage = routes[-1].stage if routes else "DISPATCH"
        dispatch_wip = db.query(StageWIP).filter(
            StageWIP.work_order_id == wo.id,
            StageWIP.stage == terminal_stage
        ).with_for_update().first()
        if not dispatch_wip:
            dispatch_wip = StageWIP(
                work_order_id=wo.id,
                stage=terminal_stage,
                ent_qty=0,
                ok_qty=0,
                inproc_qty=0,
                onhand_qty=0,
                rejected_qty=0,
                available_wip=0
            )
            db.add(dispatch_wip)
            db.flush()
        dispatch_wip.ent_qty += req.dispatched_quantity
        dispatch_wip.ok_qty += req.dispatched_quantity
        dispatch_wip.moved_out_qty += req.dispatched_quantity

        # Record in Dispatch table
        order = wo.order
        customer_po = req.customer_po or (order.customer_po if order else "N/A")
        now = datetime.now()

        dispatch_entry = Dispatch(
            work_order_id=wo.id,
            client_request_id=req.client_request_id.strip() if req.client_request_id else None,
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

        try:
            db.commit()
        except IntegrityError:
            # A concurrent request with the same idempotency key won the race.
            db.rollback()
            existing_dispatch = db.query(Dispatch).filter(
                Dispatch.client_request_id == req.client_request_id.strip()
            ).first()
            if not existing_dispatch:
                raise
            wo_existing = db.query(WorkOrder).filter(WorkOrder.id == existing_dispatch.work_order_id).first()
            pr_existing = db.query(PackingRecord).filter(PackingRecord.work_order_id == existing_dispatch.work_order_id).first()
            return DispatchResponse(
                success=True,
                invoice_number=existing_dispatch.invoice_number or req.invoice_number,
                wo_number=wo_existing.wo_number if wo_existing else req.wo_number,
                client_request_id=existing_dispatch.client_request_id,
                dispatched_quantity=existing_dispatch.dispatched_qty,
                remaining_ready_for_dispatch=pr_existing.ready_for_dispatch_qty if pr_existing else 0,
                wo_status=wo_existing.status.value if wo_existing else "unknown",
                message=f"Duplicate request detected with token '{req.client_request_id}'. Returning original transaction."
            )
        db.refresh(packing_rec)
        db.refresh(wo)

        return DispatchResponse(
            success=True,
            invoice_number=req.invoice_number,
            wo_number=wo.wo_number,
            client_request_id=req.client_request_id,
            dispatched_quantity=req.dispatched_quantity,
            remaining_ready_for_dispatch=packing_rec.ready_for_dispatch_qty,
            wo_status=wo.status.value,
            message=f"Successfully dispatched {req.dispatched_quantity} pieces under Invoice '{req.invoice_number}'. Remaining ready: {packing_rec.ready_for_dispatch_qty}."
        )

    @staticmethod
    def get_dispatch_history(db: Session, limit: int = 200, offset: int = 0) -> List[DispatchHistoryItem]:
        records = (
            db.query(Dispatch).join(WorkOrder).order_by(Dispatch.dispatch_date.desc())
            .offset(offset).limit(limit).all()
        )
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
