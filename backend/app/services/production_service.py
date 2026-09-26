import uuid
from datetime import datetime, date
from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.production import ProductionUpdate, ProductionStatus
from app.models.packing import PackingRecord
from app.models.nc import NCRecord, next_nc_number
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.production import (
    MovePartsRequest, MovementResponse,
    RecordStageProductionRequest, ProductionEntryResponse
)
from app.services.rejection_service import validate_active_rejection_type
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
    def _enforce_release_gate(wo: WorkOrder) -> None:
        """Production is blocked until the release chain (Engineering Release ->
        Manufacturing Release -> WO Released) is complete.

        Backward-compatible activation for ORDINARY WOs: the chain only applies once a
        WO has actually entered it (Engineering Release recorded) -- a WO that never
        uses it (the existing intake-and-produce flow) is completely unaffected, so
        existing production facts and tests are never silently changed.

        Replacement WOs are the one exception: `is_replacement` WOs ALWAYS require the
        full chain, starting from creation -- a replacement WO must never be producible
        before Engineering Release, even though it was never explicitly put through
        Engineering Release yet (that's the whole point: it's blocked until someone
        does)."""
        requires_full_chain = wo.is_replacement or wo.engineering_released_at is not None
        if not requires_full_chain:
            return
        if wo.engineering_released_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work Order '{wo.wo_number}' is blocked pending Engineering Release."
            )
        if wo.manufacturing_released_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work Order '{wo.wo_number}' is blocked pending Manufacturing Release."
            )
        if wo.release_date is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work Order '{wo.wo_number}' is blocked pending WO Release."
            )

    @staticmethod
    def get_stage_dashboard(db: Session, wo_number: str, stage: str):
        """Deterministic unified summary for one WO/stage -- Target, Produced, Rejected,
        Good, WIP, Yet to Produce, Remaining Movable -- reused directly from the same
        authoritative StageWIP/WORoute rows Entry/Move/Tracking already read from. No
        new quantity engine; purely a read/reshape."""
        from app.schemas.production import StageDashboard

        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number.strip()).first()
        if not wo:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Work Order '{wo_number}' not found.")

        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        route_stages = [r.stage for r in routes]
        matched_stage = match_route_stage(stage, route_stages) or stage.strip().upper()

        route_rec = next((r for r in routes if r.stage == matched_stage), None)
        wip = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == matched_stage).first()

        target = route_rec.stage_target_qty if route_rec else wo.physical_wo_qty
        good = wip.ok_qty if wip else 0
        rejected = wip.rejected_qty if wip else 0
        produced = good + rejected
        # WIP = material physically present at this stage that hasn't been produced
        # yet (StageWIP.inproc_qty = ent - ok - rej) -- NOT the same figure as "Yet
        # to Produce" below, even though they can coincide numerically at a stage
        # whose entered quantity already equals its full target. They diverge
        # wherever entered quantity lags the target (e.g. a downstream stage before
        # upstream has finished feeding it): WIP reflects what has physically
        # arrived, Yet to Produce reflects what is still owed against the overall
        # target regardless of whether it has arrived yet.
        wip_qty = wip.inproc_qty if wip else 0
        yet_to_produce = max(target - produced, 0)
        # Remaining Movable = completed good sitting on-hand, not yet moved
        # downstream (StageWIP.onhand_qty) -- rejected quantity is never included.
        remaining_movable = wip.onhand_qty if wip else 0

        return StageDashboard(
            wo_number=wo.wo_number, stage=matched_stage, target_qty=target,
            total_produced=produced, total_rejected=rejected, total_good=good,
            wip_qty=wip_qty, yet_to_produce=yet_to_produce, remaining_movable_qty=remaining_movable
        )

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

        # STEP 4: Same-WO Validation
        if req.target_wo_number and req.target_wo_number.strip() != req.wo_number.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stage movement cannot cross Work Orders."
            )

        if wo.status in (WOStatus.CLOSED, WOStatus.DISPATCHED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot move parts for Work Order '{req.wo_number}' with status '{wo.status.value}'."
            )
        ProductionService._enforce_release_gate(wo)
        if req.rejected_quantity > 0:
            validate_active_rejection_type(db, req.defect_code)

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
        # If parts were already completed and sitting On-Hand from prior stage production entry,
        # we do not double-increment ok_qty. Only increment ok_qty for direct movements where
        # production was not previously entered.
        additional_ok = max(req.quantity_moved - from_wip.onhand_qty, 0)
        from_wip.ok_qty += additional_ok
        from_wip.rejected_qty += req.rejected_quantity

        # At destination stage:
        # Ent += quantity_moved (entered process)
        to_wip.ent_qty += req.quantity_moved

        # 7. Quality Gate: Rejections at FI create NC and NEVER enter Packing/BSR!
        # If moving from manufacturing/inspection into Packing / BSR, update PackingRecord
        is_entering_packing = (
            matched_from.upper() not in ("PACKING", "BSR", "PACKING / BSR", "PACKING/BSR", "DISPATCH")
            and matched_to.upper() in ("PACKING", "BSR", "PACKING / BSR", "PACKING/BSR", "DISPATCH")
        )
        if is_entering_packing:
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
            # operator_id is always the authenticated caller, never client-supplied: it is
            # a foreign key to users.id, and trusting a client-sent value would let any
            # authenticated user attribute a movement to an arbitrary other account.
            operator_id=current_user.id if current_user else None,
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
            nc_num = next_nc_number(db)
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

        try:
            db.commit()
        except IntegrityError:
            # A concurrent request with the same idempotency key won the race.
            db.rollback()
            existing_mov = db.query(ProductionMovement).filter(
                ProductionMovement.client_request_id == req.client_request_id.strip()
            ).first()
            if not existing_mov:
                raise
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

    @staticmethod
    def record_stage_production(db: Session, req: RecordStageProductionRequest, current_user: Optional[User] = None) -> ProductionEntryResponse:
        now = datetime.now()

        # 1. Idempotency Check for Production Entry
        if req.client_request_id:
            existing_entry = db.query(ProductionUpdate).filter(
                ProductionUpdate.client_request_id == req.client_request_id.strip()
            ).first()
            if existing_entry:
                wo_existing = db.query(WorkOrder).filter(WorkOrder.id == existing_entry.work_order_id).first()
                wip_existing = db.query(StageWIP).filter(
                    StageWIP.work_order_id == existing_entry.work_order_id,
                    StageWIP.stage == existing_entry.stage
                ).first()
                return ProductionEntryResponse(
                    success=True,
                    entry_id=str(existing_entry.id),
                    client_request_id=existing_entry.client_request_id,
                    wo_number=wo_existing.wo_number if wo_existing else req.wo_number,
                    stage=existing_entry.stage,
                    good_qty=existing_entry.good_qty,
                    rejected_quantity=existing_entry.reject_qty,
                    stage_ok_total=wip_existing.ok_qty if wip_existing else existing_entry.good_qty,
                    stage_rejection_total=wip_existing.rejected_qty if wip_existing else existing_entry.reject_qty,
                    stage_onhand_available=wip_existing.onhand_qty if wip_existing else 0,
                    stage_inproc_remaining=wip_existing.inproc_qty if wip_existing else 0,
                    timestamp=existing_entry.created_at or now,
                    message=f"Duplicate production entry detected with token '{req.client_request_id}'. Returning original transaction."
                )

        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.wo_number.strip()).with_for_update().first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{req.wo_number}' not found."
            )
        if wo.status in (WOStatus.CLOSED, WOStatus.DISPATCHED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot record production for Work Order '{req.wo_number}' with status '{wo.status.value}'."
            )
        ProductionService._enforce_release_gate(wo)
        if req.rejected_quantity > 0:
            validate_active_rejection_type(db, req.defect_code)

        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        route_stages = [r.stage for r in routes]
        matched_stage = match_route_stage(req.stage, route_stages)
        if not matched_stage:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stage '{req.stage}' is not part of the route for WO '{req.wo_number}'. Valid route: {' -> '.join(route_stages)}"
            )
        
        total_proc = req.good_qty + req.rejected_quantity
        if total_proc <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Good quantity and rejected quantity cannot both be zero."
            )

        wip = db.query(StageWIP).filter(
            StageWIP.work_order_id == wo.id,
            StageWIP.stage == matched_stage
        ).with_for_update().first()

        if not wip:
            init_ent = wo.physical_wo_qty if route_stages and route_stages[0] == matched_stage else 0
            wip = StageWIP(
                work_order_id=wo.id,
                stage=matched_stage,
                ent_qty=init_ent,
                ok_qty=0,
                inproc_qty=init_ent,
                onhand_qty=0,
                rejected_qty=0,
                available_wip=init_ent
            )
            db.add(wip)
            db.flush()

        # Authoritative production ceiling: a fresh production entry can only convert
        # material that is still physically unprocessed at this stage (inproc_qty =
        # ent_qty - ok_qty - rejected_qty), never `available_wip`. available_wip also
        # includes onhand_qty -- completed-but-not-yet-moved stock -- which exists
        # precisely because earlier production already consumed that capacity; letting
        # a new entry validate against it double-counts already-completed pieces and
        # allows cumulative OK to run past ent_qty (and past the OMS target derived
        # from it) with no ceiling. This is the same ent/ok/rej accounting the OMS
        # Engine already uses to compute inproc_qty -- not a new formula.
        if total_proc > wip.inproc_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot process {total_proc} pieces ({req.good_qty} Good + {req.rejected_quantity} Rej). Only {wip.inproc_qty} pieces of unprocessed material remain at stage '{matched_stage}' (target consumed: {wip.ok_qty + wip.rejected_qty} of {wip.ent_qty})."
            )

        wip.ok_qty += req.good_qty
        wip.rejected_qty += req.rejected_quantity

        # Record ProductionUpdate log
        entry = ProductionUpdate(
            work_order_id=wo.id,
            client_request_id=req.client_request_id.strip() if req.client_request_id else None,
            stage=matched_stage,
            machine=req.machine_id,
            operator_id=current_user.id if current_user else None,
            operator_name=req.operator_name or (current_user.full_name if current_user else "Floor Operator"),
            shift=req.shift or "Shift A",
            good_qty=req.good_qty,
            reject_qty=req.rejected_quantity,
            status=ProductionStatus.COMPLETED,
            remarks=req.remarks
        )
        db.add(entry)

        # Log NC if rejected
        if req.rejected_quantity > 0:
            nc_num = next_nc_number(db)
            nc_record = NCRecord(
                nc_number=nc_num,
                work_order_id=wo.id,
                stage=matched_stage,
                defect_code=req.defect_code or "DEF-POROSITY",
                qty=req.rejected_quantity,
                root_cause=req.remarks or f"Stage production rejection at {matched_stage}",
                disposition="Scrap",
                responsibility="Production",
                status="Open"
            )
            db.add(nc_record)

        # Recompute OMS state
        OMSIntegrationService.recompute_work_order(db, wo)

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Floor Operator",
            action="STAGE_PRODUCTION_ENTRY",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            old_value=f"Stage: {matched_stage}, Prev OK: {wip.ok_qty - req.good_qty}, Prev Rej: {wip.rejected_qty - req.rejected_quantity}",
            new_value=f"Completed Good: {req.good_qty}, Rej: {req.rejected_quantity}, Total OK: {wip.ok_qty}",
            details=f"Production Entry on Machine {req.machine_id or 'Cell'} by {req.operator_name or 'Operator'}"
        )
        db.add(audit)

        try:
            db.commit()
        except IntegrityError:
            # A concurrent request with the same idempotency key won the race.
            db.rollback()
            existing_entry = db.query(ProductionUpdate).filter(
                ProductionUpdate.client_request_id == req.client_request_id.strip()
            ).first()
            if not existing_entry:
                raise
            wo_existing = db.query(WorkOrder).filter(WorkOrder.id == existing_entry.work_order_id).first()
            wip_existing = db.query(StageWIP).filter(
                StageWIP.work_order_id == existing_entry.work_order_id,
                StageWIP.stage == existing_entry.stage
            ).first()
            return ProductionEntryResponse(
                success=True,
                entry_id=str(existing_entry.id),
                client_request_id=existing_entry.client_request_id,
                wo_number=wo_existing.wo_number if wo_existing else req.wo_number,
                stage=existing_entry.stage,
                good_qty=existing_entry.good_qty,
                rejected_quantity=existing_entry.reject_qty,
                stage_ok_total=wip_existing.ok_qty if wip_existing else existing_entry.good_qty,
                stage_rejection_total=wip_existing.rejected_qty if wip_existing else existing_entry.reject_qty,
                stage_onhand_available=wip_existing.onhand_qty if wip_existing else 0,
                stage_inproc_remaining=wip_existing.inproc_qty if wip_existing else 0,
                timestamp=existing_entry.created_at or now,
                message=f"Duplicate production entry detected with token '{req.client_request_id}'. Returning original transaction."
            )
        db.refresh(wip)
        db.refresh(wo)

        return ProductionEntryResponse(
            success=True,
            entry_id=str(entry.id),
            client_request_id=req.client_request_id,
            wo_number=wo.wo_number,
            stage=matched_stage,
            good_qty=req.good_qty,
            rejected_quantity=req.rejected_quantity,
            stage_ok_total=wip.ok_qty,
            stage_rejection_total=wip.rejected_qty,
            stage_onhand_available=wip.onhand_qty,
            stage_inproc_remaining=wip.inproc_qty,
            timestamp=now,
            message=f"Successfully recorded stage production for {wo.wo_number} at {matched_stage}: {req.good_qty} Good, {req.rejected_quantity} Rejected."
        )
