import math
import uuid
from typing import List, Optional
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import or_, cast, String
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
    OARListItem, OARWorkOrderSummary, OARGenealogyResponse,
    PlanningSummaryResponse, MovableWorkOrderItem
)
from app.schemas.production import WIPMatrixResponse, WOWIPRow
from app.services.oms_integration_service import (
    calculate_delivery_risk,
    calculate_rag_status,
    calculate_stage_targets,
    OMSIntegrationService,
    DEFAULT_YIELDS
)

import re

SCHEDULE_KEYWORDS_REGEX = re.compile(
    r'^(SCH|SCHDULE|SCHEDULE|FORECAST|PLANNED)([\s\-_/]|$)|'
    r'(\b(JAN|FEB|MAR|APR|MAY|JUN|JULY|AUG|SEP|OCT|NOV|DEC)\s+(SCH|SCHEDULE|SCHDULE)\b)|'
    r'^(AWAITING[-_ ]PO)',
    re.IGNORECASE
)

STANDARD_STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]

def compute_po_coverage_status(order: Optional[Order]) -> str:
    """Determines authoritative PO coverage status for an Order (OAR):
    - PO_MATCHED: Authoritative PO Master line is validly linked (po_line exists, po exists and is not cancelled,
      and customer/part IDs match).
    - SCHEDULED_AWAITING_PO: Sourced from a schedule / forecast reference awaiting formal PO creation
      (authoritative source_type/schedule_id/oar_po_status or heuristic schedule indicator).
    - COMMERCIAL_PO_PENDING: Commercial PO reference recorded, awaiting PO Master entry / linking.
    - UNCONFIRMED: Missing, placeholder, or conflicting reference data.
    """
    if not order:
        return "UNCONFIRMED"

    # 1. Authoritative PO Master match validation
    if (
        order.po_line_id is not None
        and order.po_line is not None
        and getattr(order.po_line, "po", None) is not None
        and getattr(order.po_line.po, "status", None) != "cancelled"
        and (order.customer_id is None or getattr(order.po_line.po, "customer_id", None) == order.customer_id)
        and (order.part_id is None or getattr(order.po_line, "part_id", None) == order.part_id)
    ):
        return "PO_MATCHED"

    # 2. Authoritative Schedule intake (takes precedence over heuristic strings)
    if (
        getattr(order, "source_type", None) == "schedule"
        or getattr(order, "schedule_id", None) is not None
        or getattr(order, "oar_po_status", None) == "awaiting_po"
    ):
        return "SCHEDULED_AWAITING_PO"

    raw_po = (order.customer_po or "").strip()

    # 3. Heuristic Schedule fallback (for legacy orders where source_type was default 'po')
    if raw_po and SCHEDULE_KEYWORDS_REGEX.search(raw_po):
        return "SCHEDULED_AWAITING_PO"

    # 4. Commercial PO reference recorded
    if raw_po and raw_po.upper() not in ("N/A", "NONE", "—", "-", ""):
        return "COMMERCIAL_PO_PENDING"

    # 5. Unconfirmed / missing
    return "UNCONFIRMED"


def compute_wo_release_status(wo: WorkOrder) -> str:
    """The WO's position in the release chain (OAR -> WO Created -> Engineering Release ->
    Manufacturing Release -> WO Released -> Production), derived only from its own
    timestamp/actor pairs -- never a separate stored flag, never inferred from any other
    field. Shared by OAR genealogy and PO traceability views so the same WO always shows
    the same release label everywhere."""
    if wo.released_by or wo.release_date:
        return "RELEASED"
    if wo.manufacturing_released_by or wo.manufacturing_released_at:
        return "AWAITING_WO_RELEASE"
    if wo.engineering_released_by or wo.engineering_released_at:
        return "AWAITING_MFG_RELEASE"
    return "AWAITING_ENG_RELEASE"


class WorkOrderService:
    @staticmethod
    def list_work_orders(
        db: Session,
        search: Optional[str] = None,
        stage: Optional[str] = None,
        customer_code: Optional[str] = None,
        status_filter: Optional[str] = None,
        casting_process: Optional[str] = None,
        release_filter: Optional[str] = None,
        sort_by: Optional[str] = None,
        exclude_dispatched: bool = False,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        date_type: Optional[str] = "wo_date",
        classification: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkOrderListItem]:
        query = db.query(WorkOrder).join(Order).join(Customer).join(Part)

        if classification:
            c = classification.strip()
            if c.upper() != "ALL":
                query = query.filter(
                    or_(
                        WorkOrder.classification.ilike(c),
                        Order.order_type.ilike(c)
                    )
                )

        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    WorkOrder.wo_number.ilike(s),
                    Order.oar_number.ilike(s),
                    Customer.customer_code.ilike(s),
                    Customer.name.ilike(s),
                    Part.part_number.ilike(s),
                    Order.customer_po.ilike(s),
                    cast(WorkOrder.created_at, String).ilike(s),
                    cast(WorkOrder.release_date, String).ilike(s),
                    cast(Order.delivery_date, String).ilike(s)
                )
            )

        if stage:
            query = query.filter(WorkOrder.current_stage == stage.upper())

        if customer_code:
            query = query.filter(Customer.customer_code == customer_code.upper())

        if status_filter:
            query = query.filter(WorkOrder.status == status_filter)

        if casting_process:
            query = query.filter(WorkOrder.casting_process == casting_process.strip().upper())

        if exclude_dispatched:
            query = query.filter(
                WorkOrder.status != WOStatus.DISPATCHED,
                WorkOrder.status != WOStatus.CLOSED,
                WorkOrder.current_stage != "Completed"
            )

        # Release filter for production planners
        if release_filter:
            rf = release_filter.strip().lower()
            if rf == "unreleased":
                query = query.filter(
                    WorkOrder.release_date.is_(None),
                    WorkOrder.released_by.is_(None),
                    ~WorkOrder.status.in_([WOStatus.RELEASED, WOStatus.IN_PRODUCTION, WOStatus.DISPATCHED, WOStatus.CLOSED]),
                    WorkOrder.current_stage != "Completed"
                )
            elif rf == "released":
                query = query.filter(
                    or_(
                        WorkOrder.release_date.isnot(None),
                        WorkOrder.released_by.isnot(None),
                        WorkOrder.status.in_([WOStatus.RELEASED, WOStatus.IN_PRODUCTION, WOStatus.READY])
                    ),
                    WorkOrder.status != WOStatus.DISPATCHED,
                    WorkOrder.status != WOStatus.CLOSED,
                    WorkOrder.current_stage != "Completed"
                )
            elif rf == "ready_for_production":
                query = query.filter(
                    or_(
                        WorkOrder.release_date.isnot(None),
                        WorkOrder.manufacturing_released_at.isnot(None),
                        WorkOrder.status.in_([WOStatus.RELEASED, WOStatus.IN_PRODUCTION, WOStatus.OPEN, WOStatus.PLANNED, WOStatus.READY])
                    ),
                    WorkOrder.status != WOStatus.DISPATCHED,
                    WorkOrder.status != WOStatus.CLOSED,
                    WorkOrder.current_stage != "Completed"
                )

        # Date-wise filtering
        if from_date or to_date:
            dtype = (date_type or "wo_date").strip().lower()
            f_dt = None
            if from_date:
                try:
                    f_dt = datetime.strptime(from_date.strip()[:10], "%Y-%m-%d")
                except Exception:
                    f_dt = None

            t_dt = None
            if to_date:
                try:
                    t_dt = datetime.strptime(to_date.strip()[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
                except Exception:
                    t_dt = None

            if dtype == "release_date":
                if f_dt:
                    query = query.filter(WorkOrder.release_date >= f_dt)
                if t_dt:
                    query = query.filter(WorkOrder.release_date <= t_dt)
            elif dtype == "delivery_date":
                if f_dt:
                    query = query.filter(Order.delivery_date >= f_dt.date())
                if t_dt:
                    query = query.filter(Order.delivery_date <= t_dt.date())
            else:  # "wo_date" (creation/generation date)
                if f_dt:
                    query = query.filter(WorkOrder.created_at >= f_dt)
                if t_dt:
                    query = query.filter(WorkOrder.created_at <= t_dt)

        # Date-wise sorting for production planning
        if sort_by == "wo_date_asc":
            query = query.order_by(WorkOrder.created_at.asc())
        elif sort_by == "release_date_desc":
            query = query.order_by(WorkOrder.release_date.desc().nullslast(), WorkOrder.created_at.desc())
        elif sort_by == "release_date_asc":
            query = query.order_by(WorkOrder.release_date.asc().nullslast(), WorkOrder.created_at.desc())
        elif sort_by == "delivery_date_asc":
            query = query.order_by(Order.delivery_date.asc().nullslast(), WorkOrder.created_at.desc())
        elif sort_by == "delivery_date_desc":
            query = query.order_by(Order.delivery_date.desc().nullslast(), WorkOrder.created_at.desc())
        elif sort_by == "wo_number_asc":
            query = query.order_by(WorkOrder.wo_number.asc())
        elif sort_by == "wo_number_desc":
            query = query.order_by(WorkOrder.wo_number.desc())
        else:
            query = query.order_by(WorkOrder.created_at.desc())

        wos = query.offset(offset).limit(limit).all()

        # Batch lookup PO dates from POMaster
        po_keys = set()
        for wo in wos:
            if wo.order and wo.order.customer_id and wo.order.customer_po:
                po_keys.add((wo.order.customer_id, wo.order.customer_po.strip()))

        po_map = {}
        if po_keys:
            from app.models.master_data import POMaster
            cust_ids = {k[0] for k in po_keys}
            po_nums = {k[1] for k in po_keys}
            po_records = db.query(POMaster).filter(
                POMaster.customer_id.in_(cust_ids),
                POMaster.po_number.in_(po_nums)
            ).all()
            for p in po_records:
                po_map[(p.customer_id, p.po_number.strip())] = p.po_date or (p.created_at.date() if p.created_at else None)

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
            po_cov_status = compute_po_coverage_status(order) if order else "UNCONFIRMED"
            src_type = order.source_type if (order and getattr(order, "source_type", None)) else ("schedule" if (order and "SCH" in (order.customer_po or "").upper()) else "po")
            cust_po = order.customer_po if order else None

            # Determine PO creation date
            po_dt = None
            if order:
                if order.po_line and getattr(order.po_line, "po", None):
                    po_dt = order.po_line.po.po_date or (order.po_line.po.created_at.date() if order.po_line.po.created_at else None)
                elif order.customer_id and order.customer_po:
                    po_dt = po_map.get((order.customer_id, order.customer_po.strip()))

            oar_dt = order.created_at if order else None
            wo_dt = wo.created_at or datetime.now()
            rel_status = compute_wo_release_status(wo)
            is_rel = bool(wo.released_by or wo.release_date or wo.status in (WOStatus.RELEASED, WOStatus.IN_PRODUCTION, WOStatus.DISPATCHED, WOStatus.CLOSED))
            ready_prod = bool(is_rel or rel_status in ("RELEASED", "AWAITING_WO_RELEASE") or wo.status in (WOStatus.OPEN, WOStatus.PLANNED))

            results.append(WorkOrderListItem(
                id=str(wo.id),
                wo_number=wo.wo_number,
                oar_number=order.oar_number if order else None,
                customer_code=order.customer.customer_code if (order and order.customer) else "N/A",
                customer_name=order.customer.name if (order and order.customer) else "VSPL Internal",
                customer_po=cust_po,
                source_type=src_type,
                po_coverage_status=po_cov_status,
                part_number=order.part.part_number if (order and order.part) else "N/A",
                part_name=order.part.description if (order and order.part) else None,
                grade=order.part.grade if (order and order.part) else None,
                order_qty=order.po_qty if order else wo.physical_wo_qty,
                physical_wo_qty=wo.physical_wo_qty,
                casting_process=getattr(wo, "casting_process", None),
                match_size=order.max_batch_size if order else None,
                current_stage=cur_stage,
                next_allowed_stage=next_stage,
                available_wip_at_current_stage=avail_wip,
                status=wo.status.value,
                delivery_risk=risk,
                shortfall=wo.shortfall or "No",
                delivery_date=order.delivery_date if order else None,
                created_at=wo_dt,
                po_date=po_dt,
                oar_date=oar_dt,
                wo_date=wo_dt,
                release_date=wo.release_date,
                release_status=rel_status,
                is_released=is_rel,
                ready_for_production=ready_prod,
                heat_number=getattr(wo, "heat_number", None),
                classification=getattr(wo, "classification", None) or getattr(order, "order_type", None) or "Production"
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
        # onhand_qty > 0 (completed good parts awaiting transfer) and has a next stage to move into.
        # Note: parts MUST be produced (via Production Entry) before they can be moved downstream.
        # Unproduced material (inproc_qty) requires production entry first!
        movable_from_stage = None
        movable_to_stage = None
        movable_wip_qty = 0
        if wo.status not in (WOStatus.DISPATCHED, WOStatus.CLOSED):
            for idx2, stg2 in enumerate(route_stages):
                if idx2 + 1 >= len(route_stages):
                    break
                wr = wip_records.get(stg2)
                onhand = wr.onhand_qty if wr else 0
                if onhand > 0:
                    movable_from_stage = stg2
                    movable_wip_qty = onhand
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
                heat_number=(getattr(m, "heat_number", None) or getattr(wo, "heat_number", None)),
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
                heat_number=(getattr(p, "heat_number", None) or getattr(wo, "heat_number", None)),
                client_request_id=p.client_request_id
            ))
        tx_list.sort(key=lambda x: x.timestamp, reverse=True)

        po_cov_status = compute_po_coverage_status(order) if order else "UNCONFIRMED"
        src_type = order.source_type if (order and getattr(order, "source_type", None)) else ("schedule" if (order and "SCH" in (order.customer_po or "").upper()) else "po")

        return WorkOrderTrackingDetail(
            id=str(wo.id),
            wo_number=wo.wo_number,
            oar_number=order.oar_number if order else None,
            customer_code=order.customer.customer_code if (order and order.customer) else "CUST-001",
            customer_name=order.customer.name if (order and order.customer) else "VSPL Internal",
            customer_po=order.customer_po if order else "PO-GEN",
            source_type=src_type,
            po_coverage_status=po_cov_status,
            part_number=order.part.part_number if (order and order.part) else "N/A",
            part_name=order.part.description if (order and order.part) else None,
            grade=order.part.grade if (order and order.part) else None,
            order_qty=order.po_qty if order else wo.physical_wo_qty,
            physical_wo_qty=wo.physical_wo_qty,
            casting_process=getattr(wo, "casting_process", None),
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
            created_at=wo.created_at or datetime.now(),
            heat_number=getattr(wo, "heat_number", None),
            classification=getattr(wo, "classification", None) or getattr(order, "order_type", None) or "Production"
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
        classification: Optional[str] = None,
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
                    Part.part_number.ilike(s),
                    Order.work_orders.any(WorkOrder.wo_number.ilike(s))
                )
            )

        if customer_code:
            query = query.filter(Customer.customer_code == customer_code.upper())

        if status_filter:
            query = query.filter(Order.status == status_filter)

        if classification:
            c = classification.strip()
            query = query.filter(Order.order_type.ilike(f"{c}%"))

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

            rel_status = compute_wo_release_status(wo)
            is_rel = bool(wo.released_by or wo.release_date or wo.status in (WOStatus.RELEASED, WOStatus.IN_PRODUCTION, WOStatus.DISPATCHED, WOStatus.CLOSED))
            ready_prod = bool(is_rel or rel_status in ("RELEASED", "AWAITING_WO_RELEASE") or wo.status in (WOStatus.OPEN, WOStatus.PLANNED))

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
                casting_process=getattr(wo, "casting_process", None),
                ok_completed=good_qty,
                rejected=rejected_qty,
                movable_wip=movable_wip,
                dispatched_qty=dispatched_total,
                wo_date=wo.created_at,
                created_at=wo.created_at,
                release_date=wo.release_date,
                is_released=is_rel,
                ready_for_production=ready_prod,
                heat_number=getattr(wo, "heat_number", None),
                classification=getattr(wo, "classification", None) or getattr(order, "order_type", None) or "Production"
            ))

        num_orig = sum(1 for w in wo_summaries if w.wo_type == "ORIGINAL")
        num_patch = sum(1 for w in wo_summaries if w.wo_type == "PATCH")
        tot_produced = sum(w.production_qty for w in wo_summaries)
        tot_good = sum(w.good_qty for w in wo_summaries)
        tot_rejected = sum(w.rejected_qty for w in wo_summaries)
        oar_fulfilled = sum(w.final_good_contribution for w in wo_summaries)
        oar_shortfall = max(order.po_qty - oar_fulfilled, 0)

        po_cov_status = compute_po_coverage_status(order)
        src_type = order.source_type if getattr(order, "source_type", None) else ("schedule" if (order and "SCH" in (order.customer_po or "").upper()) else "po")
        po_matched_flag = (po_cov_status == "PO_MATCHED")
        oar_po_st = order.oar_po_status if getattr(order, "oar_po_status", None) else None

        # Determine PO creation date for order
        po_date = None
        if order.po_line and getattr(order.po_line, "po", None):
            po_date = order.po_line.po.po_date or (order.po_line.po.created_at.date() if order.po_line.po.created_at else None)
        elif order.customer_id and order.customer_po:
            from app.models.master_data import POMaster
            po_rec = db.query(POMaster).filter(
                POMaster.customer_id == order.customer_id,
                POMaster.po_number == order.customer_po.strip()
            ).first()
            if po_rec:
                po_date = po_rec.po_date or (po_rec.created_at.date() if po_rec.created_at else None)

        order_classification = getattr(order, "order_type", None) or "Production"

        return OARListItem(
            oar_number=order.oar_number or "—",
            order_id=str(order.id),
            customer_code=order.customer.customer_code if order.customer else "N/A",
            customer_name=order.customer.name if order.customer else "N/A",
            customer_po=order.customer_po,
            source_type=src_type,
            oar_po_status=oar_po_st,
            po_matched=po_matched_flag,
            po_coverage_status=po_cov_status,
            order_type=order_classification,
            classification=order_classification,
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
            commitment_date=order.commitment_date,
            created_at=order.created_at or datetime.now(),
            po_date=po_date,
            oar_date=order.created_at,
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
            source_type=summary.source_type,
            oar_po_status=summary.oar_po_status,
            po_matched=summary.po_matched,
            po_coverage_status=summary.po_coverage_status,
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
            commitment_date=summary.commitment_date,
            created_at=summary.created_at,
            po_date=summary.po_date,
            oar_date=summary.oar_date,
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

    @staticmethod
    def get_planning_summary(db: Session) -> PlanningSummaryResponse:
        """Computes live planning metrics for production planners:
        - unreleased_count: WOs pending planner release
        - released_count: WOs released into production
        - producing_today_count: distinct WOs that had production entries or movements logged today
        - ready_for_production_count: WOs ready for release / production
        - active_in_production_count: floor WIP WOs
        - total_active_wos: all non-dispatched WOs
        - total_dispatched_wos: dispatched/closed WOs
        """
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = str(date.today())

        unreleased_count = db.query(WorkOrder).filter(
            WorkOrder.release_date.is_(None),
            WorkOrder.released_by.is_(None),
            ~WorkOrder.status.in_([WOStatus.RELEASED, WOStatus.IN_PRODUCTION, WOStatus.DISPATCHED, WOStatus.CLOSED]),
            WorkOrder.current_stage != "Completed"
        ).count()

        released_count = db.query(WorkOrder).filter(
            or_(
                WorkOrder.release_date.isnot(None),
                WorkOrder.released_by.isnot(None),
                WorkOrder.status.in_([WOStatus.RELEASED, WOStatus.IN_PRODUCTION, WOStatus.READY])
            ),
            WorkOrder.status != WOStatus.DISPATCHED,
            WorkOrder.status != WOStatus.CLOSED,
            WorkOrder.current_stage != "Completed"
        ).count()

        ready_for_production_count = db.query(WorkOrder).filter(
            or_(
                WorkOrder.release_date.isnot(None),
                WorkOrder.manufacturing_released_at.isnot(None),
                WorkOrder.status.in_([WOStatus.RELEASED, WOStatus.IN_PRODUCTION, WOStatus.OPEN, WOStatus.PLANNED, WOStatus.READY])
            ),
            WorkOrder.status != WOStatus.DISPATCHED,
            WorkOrder.status != WOStatus.CLOSED,
            WorkOrder.current_stage != "Completed"
        ).count()

        active_in_production_count = db.query(WorkOrder).filter(
            WorkOrder.status.in_([WOStatus.IN_PRODUCTION, WOStatus.RELEASED]),
            WorkOrder.current_stage != "Completed"
        ).count()

        total_active_wos = db.query(WorkOrder).filter(
            WorkOrder.status != WOStatus.DISPATCHED,
            WorkOrder.status != WOStatus.CLOSED,
            WorkOrder.current_stage != "Completed"
        ).count()

        total_dispatched_wos = db.query(WorkOrder).filter(
            or_(
                WorkOrder.status.in_([WOStatus.DISPATCHED, WOStatus.CLOSED]),
                WorkOrder.current_stage == "Completed"
            )
        ).count()

        prod_update_wo_ids = {
            r[0] for r in db.query(ProductionUpdate.work_order_id).filter(
                ProductionUpdate.created_at >= today_start
            ).distinct().all() if r[0]
        }
        movement_wo_ids = {
            r[0] for r in db.query(ProductionMovement.work_order_id).filter(
                or_(
                    ProductionMovement.created_at >= today_start,
                    ProductionMovement.movement_date == today_str
                )
            ).distinct().all() if r[0]
        }
        producing_today_count = len(prod_update_wo_ids.union(movement_wo_ids))

        return PlanningSummaryResponse(
            unreleased_count=unreleased_count,
            released_count=released_count,
            producing_today_count=producing_today_count,
            ready_for_production_count=ready_for_production_count,
            active_in_production_count=active_in_production_count,
            total_active_wos=total_active_wos,
            total_dispatched_wos=total_dispatched_wos
        )

    @staticmethod
    def list_movable_work_orders(db: Session, limit: int = 50) -> List[MovableWorkOrderItem]:
        """Returns active work orders that currently have produced parts / WIP waiting
        at an origin stage to be moved to the next stage along the sequential route.
        Sorted priority-wise by earliest delivery date and largest waiting quantity."""
        active_wos = (
            db.query(WorkOrder)
            .join(Order)
            .join(Customer)
            .join(Part)
            .filter(
                WorkOrder.status.notin_([WOStatus.DISPATCHED, WOStatus.CLOSED]),
                WorkOrder.current_stage != "Completed"
            )
            .all()
        )
        items = []
        for wo in active_wos:
            routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
            route_stages = [r.stage for r in routes] if routes else ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]
            wip_records = {w.stage: w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}

            for idx2, stg2 in enumerate(route_stages):
                if idx2 + 1 >= len(route_stages):
                    break
                wr = wip_records.get(stg2)
                onhand = wr.onhand_qty if wr else 0
                if onhand > 0:
                    dest_stage = route_stages[idx2 + 1]
                    order = wo.order
                    items.append(MovableWorkOrderItem(
                        wo_id=str(wo.id),
                        wo_number=wo.wo_number,
                        oar_number=order.oar_number if order else None,
                        customer_code=order.customer.customer_code if (order and order.customer) else "N/A",
                        customer_name=order.customer.name if (order and order.customer) else "VSPL Internal",
                        part_number=order.part.part_number if (order and order.part) else "N/A",
                        part_name=order.part.description if (order and order.part) else None,
                        from_stage=stg2,
                        to_stage=dest_stage,
                        movable_wip=onhand,
                        current_stage=wo.current_stage or stg2,
                        heat_number=wo.heat_number,
                        delivery_date=order.delivery_date if order else None,
                        created_at=wo.created_at,
                    ))

        items.sort(key=lambda x: (x.delivery_date or date(2099, 12, 31), -x.movable_wip))
        for rank, item in enumerate(items, start=1):
            item.priority_rank = rank
        return items[:limit]
