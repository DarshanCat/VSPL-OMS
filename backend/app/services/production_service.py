import uuid
from datetime import datetime, date
from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.nc import NCRecord
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.production import MovePartsRequest, MovementResponse
from app.services.oms_integration_service import (
    OMSIntegrationService,
    match_route_stage,
    calculate_stage_targets
)

def _get_next_movement_id(db: Session) -> str:
    count = db.query(ProductionMovement).count()
    return f"MOV-{count + 1:06d}"

class ProductionService:
    @staticmethod
    def move_parts(db: Session, req: MovePartsRequest, current_user: Optional[User] = None) -> MovementResponse:
        now = datetime.now()

        # 1. Idempotency Check: Prevent duplicate submissions on double-click / network retry
        if req.client_request_id:
            existing_mov = db.query(ProductionMovement).filter(
                ProductionMovement.client_request_id == req.client_request_id.strip()
            ).first()
            if existing_mov:
                wo_existing = db.query(WorkOrder).filter(WorkOrder.id == existing_mov.work_order_id).first()
                from_wip_ex = db.query(StageWIP).filter(
                    StageWIP.work_order_id == wo_existing.id,
                    StageWIP.stage == existing_mov.from_stage
                ).first()
                to_wip_ex = db.query(StageWIP).filter(
                    StageWIP.work_order_id == wo_existing.id,
                    StageWIP.stage == existing_mov.to_stage
                ).first()

                return MovementResponse(
                    success=True,
                    movement_id=existing_mov.movement_id,
                    client_request_id=existing_mov.client_request_id,
                    wo_number=wo_existing.wo_number if wo_existing else req.wo_number,
                    part_number=wo_existing.order.part.part_number if (wo_existing and wo_existing.order and wo_existing.order.part) else "N/A",
                    from_stage=existing_mov.from_stage,
                    to_stage=existing_mov.to_stage,
                    quantity_moved=existing_mov.quantity_moved,
                    rejected_quantity=existing_mov.rejected_quantity,
                    available_wip_remaining=from_wip_ex.available_wip if from_wip_ex else 0,
                    to_stage_available_wip=to_wip_ex.available_wip if to_wip_ex else 0,
                    current_stage=wo_existing.current_stage if wo_existing else "N/A",
                    timestamp=existing_mov.created_at or now,
                    message=f"Duplicate request detected with token '{req.client_request_id}'. Returning original transaction '{existing_mov.movement_id}'."
                )

        # 2. Fetch Work Order with locking
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.wo_number.strip()).with_for_update().first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{req.wo_number}' not found."
            )

        if wo.status in (WOStatus.CLOSED, WOStatus.DISPATCHED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot move parts for Work Order '{req.wo_number}' with status '{wo.status.value}'."
            )

        # 3. Validate Work Order Route
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        if not routes:
            default_stages = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
            targets = calculate_stage_targets(wo.physical_wo_qty, route=default_stages)
            routes = []
            for seq, stg in enumerate(default_stages, start=1):
                r = WORoute(
                    work_order_id=wo.id,
                    stage=stg,
                    sequence=seq,
                    stage_target_qty=targets.get(stg, wo.physical_wo_qty),
                    stage_status="Pending" if seq > 1 else "In-Progress"
                )
                db.add(r)
                routes.append(r)
            db.flush()

        route_stage_names = [r.stage for r in routes]
        matched_from = match_route_stage(req.from_stage, route_stage_names)
        matched_to = match_route_stage(req.to_stage, route_stage_names)

        if not matched_from:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stage '{req.from_stage}' is not part of the released route for WO '{req.wo_number}'. Configured route: {' -> '.join(route_stage_names)}"
            )

        if not matched_to:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target stage '{req.to_stage}' is not part of the released route for WO '{req.wo_number}'. Configured route: {' -> '.join(route_stage_names)}"
            )

        if matched_from == matched_to:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Source stage and target stage cannot be identical ('{matched_from}')."
            )

        from_idx = route_stage_names.index(matched_from)
        to_idx = route_stage_names.index(matched_to)

        if to_idx != from_idx + 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid stage sequence: Cannot jump directly from '{matched_from}' to '{matched_to}'. Next allowed stage on this Work Order's route is '{route_stage_names[from_idx + 1]}'."
            )

        # 4. Fetch or initialize StageWIP for all route stages
        wip_records = {w.stage: w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).with_for_update().all()}
        
        from_wip = wip_records.get(matched_from)
        if not from_wip:
            initial_ent = wo.physical_wo_qty if from_idx == 0 else 0
            from_wip = StageWIP(
                work_order_id=wo.id,
                stage=matched_from,
                ent_qty=initial_ent,
                ok_qty=0,
                inproc_qty=initial_ent,
                onhand_qty=0,
                rejected_qty=0,
                available_wip=initial_ent,
                received_qty=initial_ent
            )
            db.add(from_wip)
            db.flush()
            wip_records[matched_from] = from_wip

        to_wip = wip_records.get(matched_to)
        if not to_wip:
            to_wip = StageWIP(
                work_order_id=wo.id,
                stage=matched_to,
                ent_qty=0,
                ok_qty=0,
                inproc_qty=0,
                onhand_qty=0,
                rejected_qty=0,
                available_wip=0,
                received_qty=0
            )
            db.add(to_wip)
            db.flush()
            wip_records[matched_to] = to_wip

        # 5. Validate Available WIP at Source Stage
        # Total pieces being processed/cleared from from_stage = req.quantity_moved + req.rejected_quantity
        total_consumed = req.quantity_moved + req.rejected_quantity
        if total_consumed > from_wip.available_wip:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot move {req.quantity_moved} pieces (with {req.rejected_quantity} rejected). Only {from_wip.available_wip} pieces are currently available at stage '{matched_from}' for WO '{req.wo_number}'."
            )

        # 6. Apply Movement in OMS Flow Counters
        # At source stage:
        # OK += quantity_moved (completed good)
        # Rej += rejected_quantity
        from_wip.ok_qty += req.quantity_moved
        from_wip.rejected_qty += req.rejected_quantity

        # At destination stage:
        # Ent += quantity_moved (entered process)
        to_wip.ent_qty += req.quantity_moved

        # 7. Quality Gate: Rejections at FI create NC and NEVER enter Packing/BSR!
        # If moving to Packing / BSR, update PackingRecord
        is_packing_target = matched_to.upper() in ("PACKING", "BSR", "PACKING / BSR", "PACKING/BSR") or matched_from.upper() == "FI"
        if is_packing_target:
            packing_rec = db.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).with_for_update().first()
            if not packing_rec:
                packing_rec = PackingRecord(
                    work_order_id=wo.id,
                    fi_approved_qty=req.quantity_moved,
                    available_for_packing=req.quantity_moved,
                    received_qty=req.quantity_moved,
                    packed_qty=0,
                    pending_qty=req.quantity_moved,
                    ready_for_dispatch_qty=0,
                    dispatched_qty=0,
                    status="In-Packing"
                )
                db.add(packing_rec)
            else:
                packing_rec.fi_approved_qty += req.quantity_moved
                packing_rec.available_for_packing += req.quantity_moved
                packing_rec.received_qty += req.quantity_moved
                packing_rec.pending_qty += req.quantity_moved
                if packing_rec.status == "Ready-for-Dispatch" and req.quantity_moved > 0:
                    packing_rec.status = "In-Packing"

        # 8. Recompute OMS Authoritative State across all stages
        OMSIntegrationService.recompute_work_order(db, wo)

        # 9. Create Immutable Movement Ledger Entry
        movement_id = _get_next_movement_id(db)
        part_id = wo.order.part_id if wo.order else None

        movement = ProductionMovement(
            movement_id=movement_id,
            client_request_id=req.client_request_id.strip() if req.client_request_id else None,
            source_type=req.source_type or "SMES_UI",
            work_order_id=wo.id,
            part_id=part_id,
            from_stage=matched_from,
            to_stage=matched_to,
            quantity_moved=req.quantity_moved,
            rejected_quantity=req.rejected_quantity,
            machine_id=req.machine_id,
            operator_id=req.operator_id if req.operator_id else (current_user.id if current_user else None),
            operator_name=req.operator_name or (current_user.full_name if current_user else "Floor Operator"),
            shift=req.shift or "Shift A",
            movement_date=str(now.date()),
            movement_time=now.strftime("%H:%M:%S"),
            remarks=req.remarks,
            created_by=current_user.id if current_user else None
        )
        db.add(movement)

        # 10. Record NC if rejected
        if req.rejected_quantity > 0:
            nc_count = db.query(NCRecord).count()
            nc_num = f"NC-{nc_count + 1:05d}"
            nc_record = NCRecord(
                nc_number=nc_num,
                work_order_id=wo.id,
                stage=matched_from,
                defect_code=req.defect_code or "DEF-POROSITY",
                qty=req.rejected_quantity,
                root_cause=req.remarks or f"Floor rejection at stage {matched_from}",
                disposition="Scrap",
                responsibility="Production",
                status="Open"
            )
            db.add(nc_record)

        # 11. Create Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "System",
            action="PRODUCTION_MOVE",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            old_value=f"From: {matched_from}, Prior Avail: {from_wip.available_wip + total_consumed}",
            new_value=f"Moved: {req.quantity_moved} to {matched_to}, Rej: {req.rejected_quantity}",
            details=f"Movement {movement_id} (Source: {req.source_type or 'SMES_UI'}) by {req.operator_name or 'Operator'}"
        )
        db.add(audit)

        db.commit()
        db.refresh(from_wip)
        db.refresh(to_wip)
        db.refresh(wo)

        part_num = wo.order.part.part_number if (wo.order and wo.order.part) else "N/A"

        return MovementResponse(
            success=True,
            movement_id=movement_id,
            client_request_id=req.client_request_id,
            wo_number=wo.wo_number,
            part_number=part_num,
            from_stage=matched_from,
            to_stage=matched_to,
            quantity_moved=req.quantity_moved,
            rejected_quantity=req.rejected_quantity,
            available_wip_remaining=from_wip.available_wip,
            to_stage_available_wip=to_wip.available_wip,
            current_stage=wo.current_stage,
            timestamp=now,
            message=f"Successfully moved {req.quantity_moved} pieces from {matched_from} to {matched_to} for {wo.wo_number}."
        )
