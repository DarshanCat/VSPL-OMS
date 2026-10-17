import uuid
import math
from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, desc

from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.customer_return import CustomerReturn, next_return_number
from app.models.order import Order, Customer, Part
from app.models.master_data import POMaster, POLine, ScheduleMaster
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.dispatch import (
    DispatchQueueItem, DispatchRequest, DispatchResponse, DispatchHistoryItem,
    InvoicePaymentUpdate, CustomerReturnCreate, CustomerReturnOut, CustomerReturnResponse
)
from app.services.oms_integration_service import OMSIntegrationService, calculate_stage_targets
from app.services.operations_service import next_wo_sequence


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

            # Resolve unit price from order po_line or POMaster
            unit_price = 0.0
            if order:
                if order.po_line and order.po_line.unit_price:
                    unit_price = float(order.po_line.unit_price)
                elif order.customer_id and order.part_id:
                    pol = db.query(POLine).join(POMaster).filter(
                        POMaster.customer_id == order.customer_id,
                        POLine.part_id == order.part_id
                    ).order_by(desc(POLine.created_at)).first()
                    if pol and pol.unit_price:
                        unit_price = float(pol.unit_price)

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
                status=pr.status,
                unit_price=unit_price
            ))
        return results

    @staticmethod
    def execute_dispatch(db: Session, req: DispatchRequest, current_user: Optional[User] = None) -> DispatchResponse:
        if not req.invoice_number or not req.invoice_number.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invoice Number is required before dispatch can be completed."
            )

        # 1. Idempotency Check
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
                    unit_price=existing_dispatch.unit_price or 0.0,
                    total_invoice_value=existing_dispatch.total_invoice_value or 0.0,
                    payment_status=existing_dispatch.payment_status or "UNPAID",
                    paid_amount=existing_dispatch.paid_amount or 0.0,
                    wo_status=wo_existing.status.value if wo_existing else "unknown",
                    message=f"Duplicate request detected with token '{req.client_request_id}'. Returning original transaction."
                )

        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.wo_number.strip()).with_for_update().first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{req.wo_number}' not found."
            )

        packing_rec = db.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).with_for_update().first()
        ready_qty = packing_rec.ready_for_dispatch_qty if packing_rec else 0

        if req.dispatched_quantity > ready_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot dispatch {req.dispatched_quantity} pieces. Only {ready_qty} pieces are ready for dispatch after Packing / BSR for WO '{req.wo_number}'."
            )

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

        packing_rec.ready_for_dispatch_qty -= req.dispatched_quantity
        packing_rec.dispatched_qty += req.dispatched_quantity

        if packing_rec.ready_for_dispatch_qty == 0 and packing_rec.pending_qty == 0:
            packing_rec.status = "Fully-Dispatched"
            wo.status = WOStatus.DISPATCHED
            wo.current_stage = "Completed"
        else:
            packing_rec.status = "Partially-Dispatched"

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

        # Commercial Value & Pricing Resolution
        order = wo.order
        customer_po = req.customer_po or (order.customer_po if order else "N/A")
        now = datetime.now()

        unit_price = 0.0
        if req.unit_price is not None and req.unit_price >= 0:
            unit_price = float(req.unit_price)
        elif order:
            if order.po_line and order.po_line.unit_price:
                unit_price = float(order.po_line.unit_price)
            elif order.customer_id and order.part_id:
                pol = db.query(POLine).join(POMaster).filter(
                    POMaster.customer_id == order.customer_id,
                    POLine.part_id == order.part_id
                ).order_by(desc(POLine.created_at)).first()
                if pol and pol.unit_price:
                    unit_price = float(pol.unit_price)

        total_invoice_val = round(req.dispatched_quantity * unit_price, 2)
        payment_status = (req.payment_status or "UNPAID").upper()
        paid_amount = float(req.paid_amount) if req.paid_amount is not None else (total_invoice_val if payment_status == "PAID" else 0.0)
        payment_date = now if payment_status == "PAID" else None

        dispatch_entry = Dispatch(
            work_order_id=wo.id,
            client_request_id=req.client_request_id.strip() if req.client_request_id else None,
            customer_po=customer_po,
            invoice_number=req.invoice_number.strip(),
            dispatched_qty=req.dispatched_quantity,
            dispatch_date=now,
            unit_price=unit_price,
            total_invoice_value=total_invoice_val,
            payment_status=payment_status,
            paid_amount=paid_amount,
            payment_date=payment_date,
            payment_reference=req.payment_reference,
            vehicle_number=req.vehicle_number,
            transporter=req.transporter,
            remarks=req.remarks,
            created_by=current_user.id if current_user else None
        )
        db.add(dispatch_entry)

        OMSIntegrationService.recompute_work_order(db, wo)

        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Dispatch Officer",
            action="DISPATCH_GOODS",
            entity="Dispatch",
            entity_id=req.invoice_number,
            old_value=f"Ready for Dispatch: {ready_qty}",
            new_value=f"Dispatched: {req.dispatched_quantity}, Total Value: {total_invoice_val}, Payment: {payment_status}",
            details=f"WO: {wo.wo_number}, Invoice: {req.invoice_number}, Price/pc: {unit_price}, Vehicle: {req.vehicle_number or 'N/A'}"
        )
        db.add(audit)

        try:
            db.commit()
        except IntegrityError:
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
                unit_price=existing_dispatch.unit_price or 0.0,
                total_invoice_value=existing_dispatch.total_invoice_value or 0.0,
                payment_status=existing_dispatch.payment_status or "UNPAID",
                paid_amount=existing_dispatch.paid_amount or 0.0,
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
            unit_price=unit_price,
            total_invoice_value=total_invoice_val,
            payment_status=payment_status,
            paid_amount=paid_amount,
            wo_status=wo.status.value,
            message=f"Successfully dispatched {req.dispatched_quantity} pieces under Invoice '{req.invoice_number}' (Value: ₹{total_invoice_val:,.2f}, Payment: {payment_status})."
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
            cust_code = order.customer.customer_code if (order and order.customer) else ""
            cust_name = order.customer.name if (order and order.customer) else "VSPL Customer"
            part_no = order.part.part_number if (order and order.part) else "N/A"
            dispatcher = d.dispatcher.full_name if d.dispatcher else "Dispatch Dept"

            # Fallback unit price calculation if not populated on older legacy rows
            u_price = d.unit_price or 0.0
            tot_val = d.total_invoice_value or (round(d.dispatched_qty * u_price, 2) if u_price else 0.0)

            results.append(DispatchHistoryItem(
                id=str(d.id),
                work_order_id=str(wo.id),
                wo_number=wo.wo_number,
                customer_code=cust_code,
                customer_name=cust_name,
                customer_po=d.customer_po or (order.customer_po if order else ""),
                part_number=part_no,
                invoice_number=d.invoice_number or "N/A",
                dispatched_qty=d.dispatched_qty,
                dispatch_date=d.dispatch_date or datetime.now(),
                dispatcher_name=dispatcher,
                unit_price=u_price,
                total_invoice_value=tot_val,
                payment_status=d.payment_status or "UNPAID",
                paid_amount=d.paid_amount or 0.0,
                payment_date=d.payment_date,
                payment_reference=d.payment_reference,
                payment_remarks=getattr(d, "remarks", None)
            ))
        return results

    @staticmethod
    def update_invoice_payment(
        db: Session,
        dispatch_id: str,
        payload: InvoicePaymentUpdate,
        current_user: Optional[User] = None
    ) -> DispatchHistoryItem:
        d = db.query(Dispatch).filter(
            or_(
                Dispatch.id == dispatch_id,
                Dispatch.invoice_number == dispatch_id
            )
        ).first()

        if not d:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dispatch invoice '{dispatch_id}' not found."
            )

        status_clean = payload.payment_status.strip().upper()
        if status_clean not in ("PAID", "UNPAID", "PARTIALLY_PAID", "OVERDUE"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment status must be 'PAID', 'UNPAID', 'PARTIALLY_PAID', or 'OVERDUE'."
            )

        old_status = d.payment_status
        d.payment_status = status_clean
        
        if payload.paid_amount is not None:
            d.paid_amount = float(payload.paid_amount)
        elif status_clean == "PAID":
            d.paid_amount = d.total_invoice_value or (d.dispatched_qty * (d.unit_price or 0.0))

        if payload.payment_date:
            d.payment_date = payload.payment_date
        elif status_clean == "PAID" and not d.payment_date:
            d.payment_date = datetime.now()

        if payload.payment_reference:
            d.payment_reference = payload.payment_reference.strip()

        if payload.payment_remarks:
            d.payment_remarks = payload.payment_remarks.strip()

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Finance/Dispatch",
            action="UPDATE_PAYMENT_STATUS",
            entity="Dispatch",
            entity_id=d.invoice_number,
            old_value=f"Status: {old_status}, Paid: {d.paid_amount}",
            new_value=f"Status: {d.payment_status}, Paid: {d.paid_amount}, Ref: {d.payment_reference}",
            details=f"Invoice: {d.invoice_number}, Payment updated by {current_user.full_name if current_user else 'User'}"
        )
        db.add(audit)
        db.commit()
        db.refresh(d)

        wo = d.work_order
        order = wo.order if wo else None
        return DispatchHistoryItem(
            id=str(d.id),
            work_order_id=str(wo.id) if wo else "",
            wo_number=wo.wo_number if wo else "",
            customer_code=order.customer.customer_code if (order and order.customer) else "",
            customer_name=order.customer.name if (order and order.customer) else "VSPL Customer",
            customer_po=d.customer_po or (order.customer_po if order else ""),
            part_number=order.part.part_number if (order and order.part) else "N/A",
            invoice_number=d.invoice_number or "N/A",
            dispatched_qty=d.dispatched_qty,
            dispatch_date=d.dispatch_date or datetime.now(),
            dispatcher_name=d.dispatcher.full_name if d.dispatcher else "Dispatch Dept",
            unit_price=d.unit_price or 0.0,
            total_invoice_value=d.total_invoice_value or 0.0,
            payment_status=d.payment_status,
            paid_amount=d.paid_amount or 0.0,
            payment_date=d.payment_date,
            payment_reference=d.payment_reference,
            payment_remarks=d.payment_remarks
        )

    # =========================================================================
    # CUSTOMER COMPLAINT & RETURN -> CONVERSION WORKFLOW
    # =========================================================================

    @staticmethod
    def lookup_product_pricing(
        db: Session,
        customer_code: Optional[str] = None,
        part_number: Optional[str] = None,
        wo_number: Optional[str] = None
    ) -> dict:
        """Lookup selling product value (unit price) from PO Master / Work Order / Schedule."""
        price = 0.0
        source = "DEFAULT"

        if wo_number:
            wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number.strip()).first()
            if wo and wo.order:
                if wo.order.po_line and wo.order.po_line.unit_price:
                    return {"unit_price": float(wo.order.po_line.unit_price), "source": "PO_LINE"}
                if wo.order.part and wo.order.customer_id:
                    pol = db.query(POLine).join(POMaster).filter(
                        POMaster.customer_id == wo.order.customer_id,
                        POLine.part_id == wo.order.part_id
                    ).order_by(desc(POLine.created_at)).first()
                    if pol and pol.unit_price:
                        return {"unit_price": float(pol.unit_price), "source": "PO_MASTER"}

        if customer_code and part_number:
            cust = db.query(Customer).filter(Customer.customer_code == customer_code.strip().upper()).first()
            prt = db.query(Part).filter(Part.part_number == part_number.strip()).first()
            if cust and prt:
                pol = db.query(POLine).join(POMaster).filter(
                    POMaster.customer_id == cust.id,
                    POLine.part_id == prt.id
                ).order_by(desc(POLine.created_at)).first()
                if pol and pol.unit_price:
                    return {"unit_price": float(pol.unit_price), "source": "PO_MASTER"}

                # Check Schedule
                sched = db.query(ScheduleMaster).filter(
                    ScheduleMaster.customer_code == cust.customer_code,
                    ScheduleMaster.part_number == prt.part_number
                ).order_by(desc(ScheduleMaster.created_at)).first()
                if sched and sched.unit_price:
                    return {"unit_price": float(sched.unit_price), "source": "SCHEDULE"}

        return {"unit_price": price, "source": source}

    @staticmethod
    def create_customer_return(
        db: Session,
        req: CustomerReturnCreate,
        current_user: Optional[User] = None
    ) -> CustomerReturnResponse:
        """Customer Complaint & Return Handling:
        1. Logs the customer complaint and returned quantity.
        2. Captures/confirms the product selling value (how much did we sell).
        3. Sends returned items directly into CONVERSION under a NEW Work Order ID.
        4. Replaces the WO Qty with the returned quantity and credits stage WIP."""
        # 1. Validate Customer
        cust = db.query(Customer).filter(Customer.customer_code == req.customer_code.strip().upper()).first()
        if not cust:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer '{req.customer_code}' not found."
            )

        # 2. Validate Part
        prt = db.query(Part).filter(Part.part_number == req.part_number.strip()).first()
        if not prt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part '{req.part_number}' not found."
            )

        # 3. Locate Original Work Order (if supplied)
        orig_wo = None
        if req.original_wo_number:
            orig_wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.original_wo_number.strip()).first()

        # 4. Resolve Selling Price / Product Value
        unit_price = 0.0
        if req.unit_price is not None and req.unit_price >= 0:
            unit_price = float(req.unit_price)
        else:
            lookup = DispatchService.lookup_product_pricing(
                db, customer_code=req.customer_code, part_number=req.part_number, wo_number=req.original_wo_number
            )
            unit_price = lookup.get("unit_price", 0.0)

        total_return_val = round(req.returned_qty * unit_price, 2)

        # 5. Generate collision-free Return ID
        ret_num = next_return_number(db)

        # 6. Resolve Destination OAR
        dest_order = None
        if req.destination_oar_number:
            dest_order = db.query(Order).filter(Order.oar_number == req.destination_oar_number.strip()).first()
        elif orig_wo and orig_wo.order:
            dest_order = orig_wo.order
        else:
            # Find an active OAR for this customer and part
            dest_order = db.query(Order).filter(
                Order.customer_id == cust.id,
                Order.part_id == prt.id
            ).order_by(desc(Order.created_at)).first()

        if not dest_order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No matching Order/OAR found for customer '{req.customer_code}' and part '{req.part_number}' to allocate the conversion replacement WO."
            )

        # 7. Generate or validate New Conversion Work Order ID
        if req.conversion_wo_number and req.conversion_wo_number.strip():
            conv_wo_num = req.conversion_wo_number.strip()
            existing_wo = db.query(WorkOrder).filter(WorkOrder.wo_number == conv_wo_num).first()
            if existing_wo:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Work Order ID '{conv_wo_num}' already exists. Please choose a unique Conversion WO ID."
                )
        else:
            conv_wo_num = next_wo_sequence(db)

        # 8. Create New Conversion Work Order replacing the returned quantity
        entry_stage = (req.entry_stage or "F1").strip().upper()
        all_stages = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
        entry_idx = all_stages.index(entry_stage) if entry_stage in all_stages else 0
        conv_route = all_stages[entry_idx:]

        classification = getattr(orig_wo, "classification", None) or getattr(dest_order, "order_type", None) or "Production"

        conv_wo = WorkOrder(
            wo_number=conv_wo_num,
            order_id=dest_order.id,
            physical_wo_qty=req.returned_qty,  # Replaces the WO quantity
            current_stage=entry_stage,
            projected_final_good=req.returned_qty,
            shortfall="No",
            status=WOStatus.IN_PRODUCTION,
            classification=classification,
            is_replacement=True,
            replacement_reason=f"Customer Return [{ret_num}]: {req.complaint_reason.strip()}",
            source_wo_id=orig_wo.id if orig_wo else None,
            released_by=current_user.full_name if current_user else "Quality / Customer Service",
            release_date=datetime.now()
        )
        db.add(conv_wo)
        db.flush()

        # Build Route for New WO
        conv_targets = calculate_stage_targets(req.returned_qty, route=conv_route)
        for seq, stg in enumerate(conv_route, start=1):
            r = WORoute(
                work_order_id=conv_wo.id,
                stage=stg,
                sequence=seq,
                stage_target_qty=conv_targets.get(stg, req.returned_qty),
                cumulative_ent_qty=req.returned_qty if seq == 1 else 0,
                cumulative_inproc_qty=req.returned_qty if seq == 1 else 0,
                stage_status="In-Progress" if seq == 1 else "Pending"
            )
            db.add(r)

        # Initialize and credit StageWIP at entry stage
        conv_wip = StageWIP(
            work_order_id=conv_wo.id,
            stage=entry_stage,
            ent_qty=req.returned_qty,
            ok_qty=0,
            inproc_qty=req.returned_qty,
            onhand_qty=0,
            rejected_qty=0,
            received_qty=req.returned_qty,
            available_wip=req.returned_qty,
            moved_out_qty=0
        )
        db.add(conv_wip)

        # 9. Create Customer Return record
        customer_return = CustomerReturn(
            return_number=ret_num,
            customer_id=cust.id,
            customer_code=cust.customer_code,
            customer_name=req.customer_name or cust.name,
            customer_po=req.customer_po or (dest_order.customer_po if dest_order else None),
            invoice_number=req.invoice_number,
            original_wo_id=orig_wo.id if orig_wo else None,
            original_wo_number=orig_wo.wo_number if orig_wo else req.original_wo_number,
            part_id=prt.id,
            part_number=prt.part_number,
            returned_qty=req.returned_qty,
            unit_price=unit_price,
            total_return_value=total_return_val,
            complaint_reason=req.complaint_reason.strip(),
            complaint_date=datetime.now(),
            status="SENT_TO_CONVERSION",
            conversion_wo_id=conv_wo.id,
            conversion_wo_number=conv_wo.wo_number,
            entry_stage=entry_stage,
            destination_oar_id=dest_order.id,
            destination_oar_number=dest_order.oar_number,
            created_by_id=current_user.id if current_user else None,
            created_by_name=current_user.full_name if current_user else "Quality Engineer"
        )
        db.add(customer_return)

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Quality/Sales",
            action="CUSTOMER_RETURN_TO_CONVERSION",
            entity="CustomerReturn",
            entity_id=ret_num,
            old_value=f"Original WO: {req.original_wo_number or 'N/A'}",
            new_value=f"New Conversion WO: {conv_wo_num}, Qty: {req.returned_qty}, Value: ₹{total_return_val:,.2f}",
            details=f"Customer: {cust.customer_code}, Complaint: {req.complaint_reason.strip()}"
        )
        db.add(audit)

        db.commit()
        db.refresh(conv_wo)
        db.refresh(customer_return)

        return CustomerReturnResponse(
            success=True,
            return_number=ret_num,
            conversion_wo_number=conv_wo.wo_number,
            returned_qty=req.returned_qty,
            unit_price=unit_price,
            total_return_value=total_return_val,
            entry_stage=entry_stage,
            destination_oar_number=dest_order.oar_number,
            message=f"Customer complaint & return recorded under '{ret_num}'. Order sent to conversion under new Work Order '{conv_wo.wo_number}' (Qty: {req.returned_qty} pcs, Product Value: ₹{total_return_val:,.2f})."
        )

    @staticmethod
    def list_customer_returns(
        db: Session,
        customer_code: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[CustomerReturnOut]:
        query = db.query(CustomerReturn).order_by(desc(CustomerReturn.created_at))

        if customer_code:
            query = query.filter(CustomerReturn.customer_code == customer_code.strip().upper())

        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    CustomerReturn.return_number.ilike(s),
                    CustomerReturn.customer_code.ilike(s),
                    CustomerReturn.customer_name.ilike(s),
                    CustomerReturn.customer_po.ilike(s),
                    CustomerReturn.invoice_number.ilike(s),
                    CustomerReturn.original_wo_number.ilike(s),
                    CustomerReturn.conversion_wo_number.ilike(s),
                    CustomerReturn.part_number.ilike(s),
                    CustomerReturn.complaint_reason.ilike(s)
                )
            )

        records = query.offset(offset).limit(limit).all()
        return [
            CustomerReturnOut(
                id=str(r.id),
                return_number=r.return_number,
                customer_code=r.customer_code,
                customer_name=r.customer_name,
                customer_po=r.customer_po,
                invoice_number=r.invoice_number,
                original_wo_number=r.original_wo_number,
                part_number=r.part_number,
                returned_qty=r.returned_qty,
                unit_price=r.unit_price,
                total_return_value=r.total_return_value,
                complaint_reason=r.complaint_reason,
                complaint_date=r.complaint_date or datetime.now(),
                status=r.status,
                conversion_wo_number=r.conversion_wo_number,
                entry_stage=r.entry_stage,
                destination_oar_number=r.destination_oar_number,
                created_by_name=r.created_by_name,
                created_at=r.created_at or datetime.now()
            )
            for r in records
        ]
