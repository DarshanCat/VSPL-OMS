import math
import uuid
from typing import List, Optional
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.production import ProductionUpdate
from app.models.order import Order, Customer, Part
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.nc import NCRecord
from app.schemas.work_order import (
    WorkOrderListItem, WorkOrderTrackingDetail, StageTimelineStep,
    WorkOrderRouteResponse, TransactionHistoryItem,
    OARListItem, OARWorkOrderSummary, OARGenealogyResponse
)
from app.schemas.production import WIPMatrixResponse, WOWIPRow
from app.services.oms_integration_service import (
    calculate_delivery_risk,
    calculate_rag_status,
    calculate_stage_targets,
    OMSIntegrationService,
    DEFAULT_YIELDS
)

STANDARD_STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]

class WorkOrderService:
    @staticmethod
    def list_work_orders(
        db: Session,
        search: Optional[str] = None,
        stage: Optional[str] = None,
        customer_code: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkOrderListItem]:
        query = db.query(WorkOrder).join(Order).join(Customer).join(Part)

        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    WorkOrder.wo_number.ilike(s),
                    Customer.customer_code.ilike(s),
                    Customer.name.ilike(s),
                    Part.part_number.ilike(s),
                    Order.customer_po.ilike(s)
                )
            )

        if stage:
            query = query.filter(WorkOrder.current_stage == stage.upper())

        if customer_code:
            query = query.filter(Customer.customer_code == customer_code.upper())

        if status_filter:
            query = query.filter(WorkOrder.status == status_filter)

        wos = query.order_by(WorkOrder.created_at.desc()).offset(offset).limit(limit).all()
        results = []

        for wo in wos:
            order = wo.order
            routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
            route_stages = [r.stage for r in routes] if routes else STANDARD_STAGES
            
            cur_stage = wo.current_stage if wo.current_stage else route_stages[0]
            next_stage = None
            if cur_stage in route_stages:
                c_idx = route_stages.index(cur_stage)
                if c_idx + 1 < len(route_stages):
                    next_stage = route_stages[c_idx + 1]

            # Available WIP at current stage
            cur_wip_rec = db.query(StageWIP).filter(
                StageWIP.work_order_id == wo.id,
                StageWIP.stage == cur_stage
            ).first()
            avail_wip = cur_wip_rec.available_wip if cur_wip_rec else (wo.physical_wo_qty if cur_stage == route_stages[0] else 0)

            risk = calculate_delivery_risk(order.delivery_date if order else None, cur_stage, wo.status.value, route_stages)

            results.append(WorkOrderListItem(
                id=str(wo.id),
                wo_number=wo.wo_number,
                oar_number=order.oar_number if order else None,
                customer_code=order.customer.customer_code if (order and order.customer) else "N/A",
                customer_name=order.customer.name if (order and order.customer) else "VSPL Internal",
                part_number=order.part.part_number if (order and order.part) else "N/A",
                part_name=order.part.description if (order and order.part) else None,
                grade=order.part.grade if (order and order.part) else None,
                order_qty=order.po_qty if order else wo.physical_wo_qty,
                physical_wo_qty=wo.physical_wo_qty,
                match_size=order.max_batch_size if order else None,
                current_stage=cur_stage,
                next_allowed_stage=next_stage,
                available_wip_at_current_stage=avail_wip,
                status=wo.status.value,
                delivery_risk=risk,
                shortfall=wo.shortfall or "No",
                delivery_date=order.delivery_date if order else None,
                created_at=wo.created_at or datetime.now()
            ))

        return results

    @staticmethod
    def get_tracking_detail(db: Session, wo_identifier: str) -> Optional[WorkOrderTrackingDetail]:
        ident = wo_identifier.strip()
        try:
            uuid_obj = uuid.UUID(ident)
            wo = db.query(WorkOrder).filter(or_(WorkOrder.wo_number == ident, WorkOrder.id == uuid_obj)).first()
        except (ValueError, AttributeError):
            wo = db.query(WorkOrder).filter(WorkOrder.wo_number == ident).first()

        if not wo:
            return None

        order = wo.order
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        if not routes:
            routes = []
            for seq, stg in enumerate(STANDARD_STAGES, start=1):
                r = WORoute(
                    work_order_id=wo.id,
                    stage=stg,
                    sequence=seq,
                    stage_target_qty=wo.physical_wo_qty,
                    stage_status="Pending" if seq > 1 else "In-Progress"
                )
                db.add(r)
                routes.append(r)
            db.commit()

        route_stages = [r.stage for r in routes]
        cur_stage = wo.current_stage or route_stages[0]
        
        cur_idx = route_stages.index(cur_stage) if cur_stage in route_stages else 0
        next_stage = route_stages[cur_idx + 1] if cur_idx + 1 < len(route_stages) else None

        wip_records = {w.stage: w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
        movements = db.query(ProductionMovement).filter(ProductionMovement.work_order_id == wo.id).order_by(ProductionMovement.created_at.asc()).all()

        # Movement-eligible stage: the earliest stage (by route sequence) that still has
        # available_wip > 0 and has a next stage to move into. This can legitimately be
        # behind `cur_stage` -- e.g. F1 still has 10 available while F2 has already begun
        # receiving material, which advances cur_stage to F2 for reporting purposes but
        # must not hide F1's still-movable quantity from the Move Parts screen.
        movable_from_stage = None
        movable_to_stage = None
        movable_wip_qty = 0
        if wo.status not in (WOStatus.DISPATCHED, WOStatus.CLOSED):
            for idx2, stg2 in enumerate(route_stages):
                if idx2 + 1 >= len(route_stages):
                    break
                wr = wip_records.get(stg2)
                av = wr.available_wip if wr else (wo.physical_wo_qty if idx2 == 0 and not wip_records else 0)
                if av > 0:
                    movable_from_stage = stg2
                    movable_wip_qty = av
                    movable_to_stage = route_stages[idx2 + 1]
                    break

        timeline_steps = []
        total_wip_held = 0
        total_rejected = 0

        for idx, r in enumerate(routes):
            stg = r.stage
            wip_rec = wip_records.get(stg)
            
            avail = wip_rec.available_wip if wip_rec else (wo.physical_wo_qty if idx == 0 and not wip_records else 0)
            inproc = wip_rec.inproc_qty if wip_rec else (wo.physical_wo_qty if idx == 0 and not wip_records else 0)
            onhand = wip_rec.onhand_qty if wip_rec else 0
            rej = (wip_rec.rejected_qty if wip_rec else 0)
            ok_qty = wip_rec.ok_qty if wip_rec else r.cumulative_ok_qty

            total_wip_held += avail
            total_rejected += rej
            
            is_cur = (stg == cur_stage)
            is_comp = (idx < cur_idx or wo.status in (WOStatus.DISPATCHED, WOStatus.CLOSED))
            is_pend = (idx > cur_idx)

            last_mov = next((m for m in reversed(movements) if m.from_stage == stg or m.to_stage == stg), None)
            rag = r.stage_status or calculate_rag_status(ok_qty, rej, inproc, r.stage_target_qty)

            timeline_steps.append(StageTimelineStep(
                stage=stg,
                sequence=r.sequence,
                name=f"Stage {stg}",
                is_current=is_cur,
                is_completed=is_comp,
                is_pending=is_pend,
                is_skip=False,
                rag_status=rag,
                target_qty=r.stage_target_qty,
                ok_completed_qty=ok_qty,
                in_process_qty=inproc,
                on_hand_wip=onhand,
                rejected_qty=rej,
                last_movement_at=last_mov.created_at if last_mov else None,
                machine=last_mov.machine_id if last_mov else None,
                operator=last_mov.operator_name if last_mov else None,
                duration_hours=2.5 if is_comp else (1.0 if is_cur else 0.0)
            ))

        yield_pct = round(100.0 * max(wo.physical_wo_qty - total_rejected, 0) / wo.physical_wo_qty, 1) if wo.physical_wo_qty > 0 else 100.0
        risk = calculate_delivery_risk(order.delivery_date if order else None, cur_stage, wo.status.value, route_stages)
        cur_wip_val = wip_records.get(cur_stage).available_wip if wip_records.get(cur_stage) else (wo.physical_wo_qty if cur_idx == 0 else 0)

        prod_updates = db.query(ProductionUpdate).filter(ProductionUpdate.work_order_id == wo.id).order_by(ProductionUpdate.created_at.desc()).all()
        
        tx_list = []
        for m in movements:
            tx_list.append(TransactionHistoryItem(
                id=str(m.id),
                timestamp=m.created_at or datetime.now(),
                transaction_type="STAGE_MOVEMENT",
                stage=m.from_stage,
                to_stage=m.to_stage,
                quantity=m.quantity_moved,
                rejected_qty=m.rejected_quantity or 0,
                defect_code=None,
                machine_id=m.machine_id,
                operator_name=m.operator_name,
                shift=m.shift,
                remarks=m.remarks,
                client_request_id=m.client_request_id
            ))
        for p in prod_updates:
            tx_list.append(TransactionHistoryItem(
                id=str(p.id),
                timestamp=p.created_at or datetime.now(),
                transaction_type="PRODUCTION_ENTRY",
                stage=p.stage,
                to_stage=None,
                quantity=p.good_qty or 0,
                rejected_qty=p.reject_qty or 0,
                defect_code=None,
                machine_id=p.machine,
                operator_name=p.operator_name,
                shift=p.shift,
                remarks=p.remarks,
                client_request_id=p.client_request_id
            ))
        tx_list.sort(key=lambda x: x.timestamp, reverse=True)

        return WorkOrderTrackingDetail(
            id=str(wo.id),
            wo_number=wo.wo_number,
            oar_number=order.oar_number if order else None,
            customer_code=order.customer.customer_code if (order and order.customer) else "CUST-001",
            customer_name=order.customer.name if (order and order.customer) else "VSPL Internal",
            customer_po=order.customer_po if order else "PO-GEN",
            part_number=order.part.part_number if (order and order.part) else "N/A",
            part_name=order.part.description if (order and order.part) else None,
            grade=order.part.grade if (order and order.part) else None,
            order_qty=order.po_qty if order else wo.physical_wo_qty,
            physical_wo_qty=wo.physical_wo_qty,
            match_size=order.max_batch_size if order else None,
            current_stage=cur_stage,
            next_allowed_stage=next_stage,
            available_wip=cur_wip_val,
            movable_from_stage=movable_from_stage,
            movable_to_stage=movable_to_stage,
            movable_wip=movable_wip_qty,
            status=wo.status.value,
            shortfall=wo.shortfall or "No",
            projected_final_good=wo.projected_final_good or max(wo.physical_wo_qty - total_rejected, 0),
            delivery_risk=risk,
            delivery_date=order.delivery_date if order else None,
            route_string=" -> ".join(route_stages),
            timeline=timeline_steps,
            transactions=tx_list,
            total_wip_on_hand=total_wip_held,
            total_rejected=total_rejected,
            yield_pct=yield_pct,
            created_at=wo.created_at or datetime.now()
        )

    @staticmethod
    def get_work_order_route(db: Session, wo_identifier: str) -> Optional[WorkOrderRouteResponse]:
        ident = wo_identifier.strip()
        try:
            uuid_obj = uuid.UUID(ident)
            wo = db.query(WorkOrder).filter(or_(WorkOrder.wo_number == ident, WorkOrder.id == uuid_obj)).first()
        except (ValueError, AttributeError):
            wo = db.query(WorkOrder).filter(WorkOrder.wo_number == ident).first()

        if not wo:
            return None

        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        route_stages = [r.stage for r in routes] if routes else STANDARD_STAGES
        targets = {r.stage: r.stage_target_qty for r in routes} if routes else calculate_stage_targets(wo.physical_wo_qty, route=STANDARD_STAGES)
        cur_stage = wo.current_stage or route_stages[0]
        next_stage = OMSIntegrationService.get_next_stage(db, wo, cur_stage)

        return WorkOrderRouteResponse(
            wo_number=wo.wo_number,
            physical_wo_qty=wo.physical_wo_qty,
            match_size=wo.order.max_batch_size if wo.order else None,
            current_stage=cur_stage,
            route_stages=route_stages,
            next_stage=next_stage,
            stage_targets=targets
        )

    @staticmethod
    def get_stage_state(db: Session, wo_identifier: str, stage_name: str) -> Optional[dict]:
        ident = wo_identifier.strip()
        try:
            uuid_obj = uuid.UUID(ident)
            wo = db.query(WorkOrder).filter(or_(WorkOrder.wo_number == ident, WorkOrder.id == uuid_obj)).first()
        except (ValueError, AttributeError):
            wo = db.query(WorkOrder).filter(WorkOrder.wo_number == ident).first()

        if not wo:
            return None

        return OMSIntegrationService.get_current_stage_state(db, wo, stage_name)

    @staticmethod
    def list_oars(
        db: Session,
        search: Optional[str] = None,
        status_filter: Optional[str] = None,
        customer_code: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[OARListItem]:
        """Read-only OAR + WO roll-up over existing Order/WorkOrder records. Computes no
        business rules of its own -- allocated/remaining/WIP/dispatch figures are pulled
        directly from the existing OMS Engine-derived data (StageWIP, ProductionUpdate,
        Dispatch), the same authoritative sources the WO tracking detail endpoint uses."""
        query = db.query(Order).join(Customer).join(Part)

        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Order.oar_number.ilike(s),
                    Order.customer_po.ilike(s),
                    Customer.customer_code.ilike(s),
                    Customer.name.ilike(s),
                    Part.part_number.ilike(s)
                )
            )

        if customer_code:
            query = query.filter(Customer.customer_code == customer_code.upper())

        if status_filter:
            query = query.filter(Order.status == status_filter)

        orders = query.order_by(Order.created_at.desc()).offset(offset).limit(limit).all()
        return [WorkOrderService.build_oar_summary(db, order) for order in orders]

    @staticmethod
    def build_oar_summary(db: Session, order: Order) -> OARListItem:
        """Authoritative OAR Genealogy & Production Aggregation:
        Rolls up all Original and Patch/Replacement WOs created under this OAR,
        including all production, stage rejections, final good contributions,
        total OAR fulfillment, and remaining shortfall without double-counting."""
        wos = db.query(WorkOrder).filter(WorkOrder.order_id == order.id).order_by(WorkOrder.created_at.asc(), WorkOrder.wo_number.asc()).all()

        wo_summaries: List[OARWorkOrderSummary] = []
        allocated_total = 0

        for wo in wos:
            allocated_total += wo.physical_wo_qty

            routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
            route_stages = [r.stage for r in routes] if routes else STANDARD_STAGES
            cur_stage = wo.current_stage or route_stages[0]

            cur_wip_rec = db.query(StageWIP).filter(
                StageWIP.work_order_id == wo.id,
                StageWIP.stage == cur_stage
            ).first()
            movable_wip = cur_wip_rec.available_wip if cur_wip_rec else 0

            prod_entries = db.query(ProductionUpdate).filter(ProductionUpdate.work_order_id == wo.id).all()
            wips = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
            movements = db.query(ProductionMovement).filter(ProductionMovement.work_order_id == wo.id).all()

            if prod_entries:
                produced_qty = sum((p.good_qty or 0) + (p.reject_qty or 0) for p in prod_entries)
                good_qty = sum(p.good_qty or 0 for p in prod_entries)
            elif movements:
                first_stg = route_stages[0] if route_stages else "F1"
                first_moves = [m for m in movements if m.from_stage == first_stg]
                produced_qty = sum(m.quantity_moved + m.rejected_quantity for m in first_moves)
                good_qty = sum(m.quantity_moved for m in movements)
            else:
                produced_qty = 0
                good_qty = 0

            # Total rejected on this WO across ALL stages
            rejected_qty = sum(w.rejected_qty for w in wips) if wips else sum(nc.qty for nc in db.query(NCRecord).filter(NCRecord.work_order_id == wo.id).all())

            # Authoritative Final Good fulfillment contribution for this WO:
            # Material ONLY counts as final good fulfillment when it has completed the entire route
            # (i.e. reached Packing / BSR / Dispatch or completed the terminal stage of that specific route).
            pr = db.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
            if pr:
                final_good = (pr.dispatched_qty or 0) + (pr.ready_for_dispatch_qty or 0) + (pr.packed_qty or 0)
                if final_good == 0 and (pr.received_qty or 0) > 0:
                    final_good = pr.received_qty or 0
            else:
                is_packing_route = any(s.upper() in ("PACKING", "BSR", "PACKING / BSR", "PACKING/BSR", "DISPATCH") for s in route_stages)
                if is_packing_route:
                    # Route has a packing stage but material has not arrived there yet -> intermediate WIP, not yet fulfilled
                    final_good = 0
                else:
                    # For custom routes terminating at FI or an earlier stage without packing
                    terminal_stages = [s for s in route_stages if s.upper() not in ("DISPATCH",)]
                    final_stage = terminal_stages[-1] if terminal_stages else (route_stages[-1] if route_stages else "F1")
                    final_wip = next((sw for sw in wips if sw.stage.upper() == final_stage.upper()), None)
                    if final_wip and final_wip.ok_qty > 0:
                        final_good = final_wip.ok_qty
                    else:
                        final_good = 0

            dispatched_total = sum(
                d.dispatched_qty or 0
                for d in db.query(Dispatch).filter(Dispatch.work_order_id == wo.id).all()
            )

            if wo.released_by or wo.release_date:
                rel_status = "RELEASED"
            elif wo.manufacturing_released_by or wo.manufacturing_released_at:
                rel_status = "AWAITING_WO_RELEASE"
            elif wo.engineering_released_by or wo.engineering_released_at:
                rel_status = "AWAITING_MFG_RELEASE"
            else:
                rel_status = "AWAITING_ENG_RELEASE"

            wo_type = "PATCH" if wo.is_replacement else "ORIGINAL"
            source_wo_num = wo.source_wo.wo_number if wo.source_wo else None

            wo_summaries.append(OARWorkOrderSummary(
                wo_id=str(wo.id),
                wo_number=wo.wo_number,
                wo_type=wo_type,
                is_replacement=bool(wo.is_replacement),
                source_wo_id=str(wo.source_wo_id) if wo.source_wo_id else None,
                source_wo_number=source_wo_num,
                replacement_qty=wo.physical_wo_qty if wo.is_replacement else 0,
                allocated_qty=wo.physical_wo_qty,
                production_qty=produced_qty,
                good_qty=good_qty,
                rejected_qty=rejected_qty,
                final_good_contribution=final_good,
                release_status=rel_status,
                current_stage=cur_stage,
                wo_status=wo.status.value,
                ok_completed=good_qty,
                rejected=rejected_qty,
                movable_wip=movable_wip,
                dispatched_qty=dispatched_total
            ))

        num_orig = sum(1 for w in wo_summaries if w.wo_type == "ORIGINAL")
        num_patch = sum(1 for w in wo_summaries if w.wo_type == "PATCH")
        tot_produced = sum(w.production_qty for w in wo_summaries)
        tot_good = sum(w.good_qty for w in wo_summaries)
        tot_rejected = sum(w.rejected_qty for w in wo_summaries)
        oar_fulfilled = sum(w.final_good_contribution for w in wo_summaries)
        oar_shortfall = max(order.po_qty - oar_fulfilled, 0)

        return OARListItem(
            oar_number=order.oar_number or "—",
            order_id=str(order.id),
            customer_code=order.customer.customer_code if order.customer else "N/A",
            customer_name=order.customer.name if order.customer else "N/A",
            customer_po=order.customer_po,
            part_number=order.part.part_number if order.part else "N/A",
            oar_qty=order.po_qty,
            allocated_qty=allocated_total,
            remaining_qty=order.po_qty - allocated_total,
            num_wos=len(wos),
            num_original_wos=num_orig,
            num_patch_wos=num_patch,
            total_produced=tot_produced,
            total_good=tot_good,
            total_rejected=tot_rejected,
            oar_fulfilled=oar_fulfilled,
            oar_shortfall=oar_shortfall,
            status=order.status.value,
            delivery_date=order.delivery_date,
            created_at=order.created_at or datetime.now(),
            work_orders=wo_summaries
        )

    @staticmethod
    def get_oar_genealogy(db: Session, oar_number: str) -> Optional[OARGenealogyResponse]:
        order = db.query(Order).filter(Order.oar_number == oar_number.strip()).first()
        if not order:
            return None
        summary = WorkOrderService.build_oar_summary(db, order)
        return OARGenealogyResponse(
            oar_number=summary.oar_number,
            order_id=summary.order_id,
            customer_code=summary.customer_code,
            customer_name=summary.customer_name,
            customer_po=summary.customer_po,
            part_number=summary.part_number,
            oar_qty=summary.oar_qty,
            num_wos=summary.num_wos,
            num_original_wos=summary.num_original_wos,
            num_patch_wos=summary.num_patch_wos,
            total_produced=summary.total_produced,
            total_good=summary.total_good,
            total_rejected=summary.total_rejected,
            oar_fulfilled=summary.oar_fulfilled,
            oar_shortfall=summary.oar_shortfall,
            status=summary.status,
            delivery_date=summary.delivery_date,
            created_at=summary.created_at,
            work_orders=summary.work_orders
        )

    @staticmethod
    def get_wip_matrix(db: Session) -> WIPMatrixResponse:
        stages = STANDARD_STAGES
        active_wos = db.query(WorkOrder).filter(WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED])).all()

        wo_rows = []
        stage_totals = {s: 0 for s in stages}
        stage_inproc_totals = {s: 0 for s in stages}
        stage_onhand_totals = {s: 0 for s in stages}
        grand_total = 0

        for wo in active_wos:
            order = wo.order
            wips = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
            
            wip_dict = {}
            inproc_dict = {}
            onhand_dict = {}
            
            for w in wips:
                stg_key = w.stage
                if stg_key in ("PACKING", "BSR", "PACKING/BSR", "PACKING / BSR"):
                    stg_key = "PACKING / BSR"
                wip_dict[stg_key] = wip_dict.get(stg_key, 0) + w.available_wip
                inproc_dict[stg_key] = inproc_dict.get(stg_key, 0) + w.inproc_qty
                onhand_dict[stg_key] = onhand_dict.get(stg_key, 0) + w.onhand_qty

            if not wip_dict:
                cur_stg = wo.current_stage or "F1"
                if cur_stg in ("PACKING", "BSR", "PACKING/BSR", "PACKING / BSR"):
                    cur_stg = "PACKING / BSR"
                wip_dict[cur_stg] = wo.physical_wo_qty
                inproc_dict[cur_stg] = wo.physical_wo_qty
                onhand_dict[cur_stg] = 0

            wo_total = sum(wip_dict.values())
            grand_total += wo_total

            for s in stages:
                val = wip_dict.get(s, 0)
                stage_totals[s] += val
                stage_inproc_totals[s] += inproc_dict.get(s, 0)
                stage_onhand_totals[s] += onhand_dict.get(s, 0)

            wo_rows.append(WOWIPRow(
                wo_id=str(wo.id),
                wo_number=wo.wo_number,
                part_number=order.part.part_number if (order and order.part) else "N/A",
                part_name=order.part.description if (order and order.part) else None,
                customer_code=order.customer.customer_code if (order and order.customer) else "N/A",
                customer_name=order.customer.name if (order and order.customer) else "VSPL Customer",
                order_qty=wo.physical_wo_qty,
                current_stage=wo.current_stage if wo.current_stage else "F1",
                status=wo.status.value,
                stage_wips=wip_dict,
                stage_inproc=inproc_dict,
                stage_onhand=onhand_dict,
                total_wip=wo_total,
                last_updated=wo.updated_at or wo.created_at
            ))

        return WIPMatrixResponse(
            stages=stages,
            work_orders=wo_rows,
            stage_totals=stage_totals,
            stage_inproc_totals=stage_inproc_totals,
            stage_onhand_totals=stage_onhand_totals,
            grand_total_wip=grand_total
        )
