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
from app.schemas.work_order import (
    WorkOrderListItem, WorkOrderTrackingDetail, StageTimelineStep,
    WorkOrderRouteResponse, TransactionHistoryItem
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
