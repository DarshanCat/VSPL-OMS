import math
import re
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple, Union
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.nc import NCRecord
from app.models.order import Order, Customer, Part, OrderStatus
from app.models.audit import AuditLog
from app.models.oms_exception import OMSException
from app.schemas.production import ReconciliationItem, PlantReconciliationResponse
from app.schemas.oms import WOOarLinkRow, LinkResult, LinkException, LinkResultItem

# Authoritative OMS Yields & Defaults from oms_core/oms_engine.py
DEFAULT_YIELDS: Dict[str, float] = {
    "F1": 0.89,
    "F2": 0.89,
    "F3": 0.97,
    "SP": 0.99,
    "FI": 0.94,
    "PACKING": 1.0,
    "BSR": 1.0,
    "PACKING / BSR": 1.0,
    "DISPATCH": 1.0
}

STAGE_DONE = ("Green", "Amber", "Red", "Converted-in", "Completed")
DISPATCH_DONE = ("Green", "Amber", "Red", "Completed")

def parse_route(route_str: Union[str, List[str]]) -> List[str]:
    """
    Authoritative OMS Route Parser:
    'F1 > F2 > F3 > SP > FI > Packing > Dispatch' -> ['F1', 'F2', 'F3', 'SP', 'FI', 'Packing', 'Dispatch']
    """
    if not route_str:
        return ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
    if isinstance(route_str, list):
        parts = [str(x).strip() for x in route_str]
    else:
        parts = [x.strip() for x in route_str.replace(",", ">").replace("->", ">").split(">")]
    stages = [s for s in parts if s and s.upper() != "DISPATCH"]
    return stages + ["DISPATCH"]

def match_route_stage(requested_stage: str, route_stages: List[str]) -> Optional[str]:
    """
    Route-aware stage matcher preserving explicit Work Order route definitions.
    """
    req = (requested_stage or "").strip().upper()
    if not req:
        return None

    # 1. Exact match (case-insensitive)
    for stg in route_stages:
        if stg.strip().upper() == req:
            return stg

    # 2. Normalized whitespace & slash match
    req_clean = req.replace(" ", "")
    for stg in route_stages:
        if stg.strip().upper().replace(" ", "") == req_clean:
            return stg

    # 3. Dynamic stage alias handling (only if the route does not contain discrete stages)
    route_upper = [s.strip().upper() for s in route_stages]
    has_separate_stages = "PACKING" in route_upper and "BSR" in route_upper

    if not has_separate_stages:
        if any(s in ("PACKING / BSR", "PACKING/BSR") for s in route_upper) and req in ("PACKING", "BSR", "PACK"):
            for stg in route_stages:
                if stg.strip().upper() in ("PACKING / BSR", "PACKING/BSR"):
                    return stg
        if "PACKING" in route_upper and req in ("PACKING / BSR", "PACKING/BSR", "BSR"):
            for stg in route_stages:
                if stg.strip().upper() == "PACKING":
                    return stg

    return None

def calculate_stage_targets(good_target: int, yields: Optional[Dict[str, float]] = None, route: Optional[List[str]] = None) -> Dict[str, int]:
    """
    Authoritative OMS Target Back-Calculation:
    Back-calculates stage target quantities from good target using stage yields over the route.
    """
    yd = yields or DEFAULT_YIELDS
    rt = route or ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
    prod = [s for s in rt if s.upper() not in ("DISPATCH", "PACKING", "BSR", "PACKING / BSR")]
    targets: Dict[str, int] = {}
    need = float(good_target)
    for st in reversed(prod):
        targets[st] = math.ceil(need)
        need = need / yd.get(st.upper(), 1.0)
    for s in rt:
        if s.upper() in ("PACKING", "BSR", "PACKING / BSR", "DISPATCH"):
            targets[s] = math.ceil(good_target)
    return targets

def calculate_rag_status(ok: int, rej: int, inproc: int, target: int) -> str:
    """
    Authoritative OMS RAG Formula (v3.2/v3.3):
    processed = OK + Rej
    shortfall = (target - processed) / target
      shortfall < 5%   -> Green
      5% <= shortfall < 10% -> Amber
      shortfall >= 10% -> Red
      processed <= 0 -> In-Process (if inproc > 0) else Pending
    """
    processed = int(ok) + int(rej)
    if processed <= 0:
        return "In-Process" if int(inproc) > 0 else "Pending"
    tgt = int(target)
    if tgt <= 0:
        return "Green"
    shortfall = (tgt - processed) / tgt
    EPS = 1e-9
    if shortfall < 0.05 - EPS:
        return "Green"
    if shortfall < 0.10 - EPS:
        return "Amber"
    return "Red"

def calculate_delivery_risk(due_date: Optional[date], current_stage: str, overall_status: str, route_stages: List[str]) -> str:
    """
    Authoritative OMS Delivery Risk:
    Compares days remaining to customer delivery against remaining stages along the WO route.
    """
    if overall_status.lower() in ("dispatched", "closed"):
        return "On Track"
    if not due_date:
        return "On Track"
    today = date.today()
    days_left = (due_date - today).days
    try:
        cur_idx = [s.upper() for s in route_stages].index(current_stage.upper())
    except ValueError:
        cur_idx = 0
    stages_remaining = max(len(route_stages) - cur_idx, 1)
    if days_left < 0:
        return "OVERDUE"
    if days_left <= stages_remaining:
        return "HIGH RISK"
    if days_left <= stages_remaining * 2:
        return "AT RISK"
    return "On Track"

class OMSIntegrationService:
    """
    Central Authoritative Manufacturing Calculation Layer bridging SMES Real-Time Transactions
    with OMS Engine v3.3 Flow Semantics.
    """

    @staticmethod
    def recompute_work_order(db: Session, wo: WorkOrder) -> None:
        """
        Authoritative OMS _recompute_wo:
        Derives live In-Process (net) and On-Hand from cumulative counters across each stage of the WO route.
        """
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        if not routes:
            return

        route_names = [r.stage for r in routes]
        wip_map = {w.stage: w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
        pr = db.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()

        # 1. Flow calculations along the route
        for i, r in enumerate(routes):
            stg = r.stage
            wip_rec = wip_map.get(stg)
            if not wip_rec:
                wip_rec = StageWIP(
                    work_order_id=wo.id,
                    stage=stg,
                    ent_qty=wo.physical_wo_qty if i == 0 else 0,
                    ok_qty=0,
                    inproc_qty=wo.physical_wo_qty if i == 0 else 0,
                    onhand_qty=0,
                    rejected_qty=0,
                    available_wip=wo.physical_wo_qty if i == 0 else 0
                )
                db.add(wip_rec)
                db.flush()
                wip_map[stg] = wip_rec

            ent = wip_rec.ent_qty
            ok = wip_rec.ok_qty
            rej = wip_rec.rejected_qty
            tgt = r.stage_target_qty

            is_packing_or_final = (
                stg.upper() in ("PACKING", "BSR", "PACKING / BSR", "PACKING/BSR", "DISPATCH")
                or i == len(routes) - 1
                or (i + 1 < len(routes) and routes[i + 1].stage.upper() == "DISPATCH")
            )

            if is_packing_or_final and pr:
                net_ip = pr.pending_qty
                on_hand = pr.ready_for_dispatch_qty
            else:
                # OMS Flow Formula: In-Process (net) = max(Ent - OK - Rej, 0)
                net_ip = max(ent - ok - rej, 0)

                # OMS Flow Formula: On-Hand = max(OK - Ent(next), 0)
                nxt_ent = 0
                if i + 1 < len(routes):
                    nxt_stg = routes[i + 1].stage
                    nxt_wip = wip_map.get(nxt_stg)
                    nxt_ent = nxt_wip.ent_qty if nxt_wip else 0
                on_hand = max(ok - nxt_ent, 0)

            # Update StageWIP
            wip_rec.inproc_qty = net_ip
            wip_rec.onhand_qty = on_hand
            wip_rec.available_wip = net_ip + on_hand
            wip_rec.received_qty = ent
            wip_rec.moved_out_qty = ok

            # Update WORoute
            r.cumulative_ent_qty = ent
            r.cumulative_ok_qty = ok
            r.cumulative_rej_qty = rej
            r.cumulative_inproc_qty = net_ip
            r.cumulative_onhand_qty = on_hand
            r.stage_status = calculate_rag_status(ok, rej, net_ip, tgt)

        # 2. Furthest data-bearing stage (OMS Snapshot Rule)
        def _has_data(stg_name: str) -> bool:
            w = wip_map.get(stg_name)
            if not w:
                return False
            return w.ok_qty > 0 or w.rejected_qty > 0 or w.inproc_qty > 0 or w.onhand_qty > 0

        furthest = None
        for r in routes:
            if _has_data(r.stage):
                furthest = r.stage

        if furthest is None:
            cur = routes[0].stage
        elif furthest == routes[-1].stage and routes[-1].stage_status in DISPATCH_DONE:
            cur = "Completed"
        else:
            cur = furthest
        wo.current_stage = cur

        # 3. Projected Final Good & Shortfall Calculation
        good = wo.physical_wo_qty
        prod_routes = [r for r in routes if r.stage.upper() not in ("DISPATCH",)]
        proj = good
        last_ok_stage = None
        for pr_route in prod_routes:
            w = wip_map.get(pr_route.stage)
            if w and w.ok_qty > 0:
                last_ok_stage = pr_route.stage

        if last_ok_stage is not None:
            w = wip_map.get(last_ok_stage)
            proj = float(w.ok_qty) if w else float(good)
            stg_idx = [r.stage for r in prod_routes].index(last_ok_stage)
            for pr_route in prod_routes[stg_idx + 1:]:
                proj *= DEFAULT_YIELDS.get(pr_route.stage.upper(), 1.0)
            proj = int(math.floor(proj))
        wo.projected_final_good = proj

        # Shortfall: projection below target or furthest stage ended Amber/Red
        short_closed = furthest is not None and any(r.stage == furthest and r.stage_status in ("Amber", "Red") for r in routes)
        wo.shortfall = "YES" if (proj < good or short_closed) else "No"

        # 4. Overall Status
        last_prod = prod_routes[-1].stage if prod_routes else None
        prod_done = False
        if last_prod:
            lp_w = wip_map.get(last_prod)
            prod_done = lp_w is not None and (lp_w.ok_qty > 0 or lp_w.rejected_qty > 0)

        if (pr and pr.dispatched_qty > 0 and pr.ready_for_dispatch_qty == 0 and pr.pending_qty == 0) or str(wo.status).lower() in ("dispatched", "wostatus.dispatched"):
            wo.status = WOStatus.DISPATCHED
            wo.current_stage = "Completed"
        elif prod_done or cur in ("DISPATCH", "Completed"):
            wo.status = WOStatus.READY
        else:
            wo.status = WOStatus.IN_PRODUCTION

    @staticmethod
    def reconcile_work_order(db: Session, wo: WorkOrder) -> ReconciliationItem:
        """
        Reconciliation Formula:
        Released Quantity = Total Live WIP (In-Process + On-Hand across all stages) + Total Rejections (NCs) + Dispatched Quantity
        """
        wips = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
        total_wip = sum(w.available_wip for w in wips)
        total_rej = sum(w.rejected_qty for w in wips)
        
        pr = db.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
        dispatched_qty = pr.dispatched_qty if pr else 0
        
        accounted = total_wip + total_rej + dispatched_qty
        variance = wo.physical_wo_qty - accounted
        is_balanced = (variance == 0)

        detail = f"Released: {wo.physical_wo_qty} | Total WIP: {total_wip} (InProc+OnHand) | Rejections: {total_rej} | Dispatched: {dispatched_qty} | Variance: {variance}"
        return ReconciliationItem(
            wo_number=wo.wo_number,
            released_qty=wo.physical_wo_qty,
            total_wip=total_wip,
            total_rejected=total_rej,
            dispatched_qty=dispatched_qty,
            accounted_qty=accounted,
            variance=variance,
            is_balanced=is_balanced,
            details=detail
        )

    @staticmethod
    def get_next_stage(db: Session, wo: WorkOrder, current_stage: str) -> Optional[str]:
        """
        Authoritative getNextStage(woId, currentStage):
        Looks up the Work Order's exact configured route (WORoute) and returns the immediate next stage.
        Never assumes next stage globally.
        """
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        if not routes:
            return None
        route_stages = [r.stage for r in routes]
        matched = match_route_stage(current_stage, route_stages)
        if not matched or matched not in route_stages:
            return None
        idx = route_stages.index(matched)
        if idx + 1 < len(route_stages):
            return route_stages[idx + 1]
        return None

    @staticmethod
    def get_current_stage_state(db: Session, wo: WorkOrder, stage_name: str) -> dict:
        """
        Authoritative getCurrentStageState(woId, stage):
        Returns the single source of truth for a stage's live operational state.
        """
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        route_stages = [r.stage for r in routes] if routes else []
        matched = match_route_stage(stage_name, route_stages) if route_stages else stage_name
        
        route_rec = db.query(WORoute).filter(
            WORoute.work_order_id == wo.id,
            WORoute.stage == (matched or stage_name)
        ).first()
        
        wip_rec = db.query(StageWIP).filter(
            StageWIP.work_order_id == wo.id,
            StageWIP.stage == (matched or stage_name)
        ).first()

        target_qty = route_rec.stage_target_qty if route_rec else (wo.physical_wo_qty or 0)
        ok_qty = wip_rec.ok_qty if wip_rec else 0
        rej_qty = wip_rec.rejected_qty if wip_rec else 0
        inproc_qty = wip_rec.inproc_qty if wip_rec else 0
        onhand_qty = wip_rec.onhand_qty if wip_rec else 0
        avail_wip = inproc_qty + onhand_qty
        # Good quantity that has already left this stage via movement -- the portion of
        # cumulative OK that is no longer sitting here as on-hand WIP. Derived from the
        # same ok_qty/onhand_qty this function already computes; not a new calculation,
        # just exposing an existing relationship (onhand_qty = max(ok_qty - next stage's
        # ent_qty, 0), so ok_qty - onhand_qty is exactly what has moved on).
        already_moved_qty = max(ok_qty - onhand_qty, 0)
        # Production-planning view (Target vs. cumulative OK), distinct from inproc_qty
        # (the physical unprocessed-material ceiling above). These can legitimately
        # differ once anything has been rejected: e.g. Target=10, 2 rejected, 5 OK ->
        # inproc_qty = 10-5-2 = 3 pieces of raw material still physically convertible,
        # while "Not Yet Produced" = 10-5 = 5 against the original target. Both are
        # real, correct answers to different questions -- not an inconsistency.
        not_yet_produced = max(target_qty - ok_qty, 0)
        rag = route_rec.stage_status if route_rec else calculate_rag_status(ok_qty, rej_qty, inproc_qty, target_qty)
        next_stage = OMSIntegrationService.get_next_stage(db, wo, matched or stage_name)

        return {
            "wo_number": wo.wo_number,
            "stage": matched or stage_name,
            "target_qty": target_qty,
            "ok_completed_qty": ok_qty,
            "rejected_qty": rej_qty,
            "in_process_qty": inproc_qty,
            "on_hand_qty": onhand_qty,
            "available_wip": avail_wip,
            "already_moved_qty": already_moved_qty,
            "not_yet_produced": not_yet_produced,
            "remaining_to_produce": not_yet_produced,
            "stage_status": rag,
            "is_current_stage": (wo.current_stage == (matched or stage_name)),
            "next_stage": next_stage
        }

    @staticmethod
    def initialize_wo_stages(db: Session, wo: WorkOrder, route_str: Optional[str] = None) -> List[WORoute]:
        """
        Atomically initializes all WORoute and StageWIP records for a Work Order within a single transaction.
        If any error occurs, rollback ensures no partial route remains.
        """
        # Delete existing if re-initializing
        db.query(WORoute).filter(WORoute.work_order_id == wo.id).delete()
        db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).delete()

        stage_list = parse_route(route_str) if route_str else ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
        targets = calculate_stage_targets(wo.physical_wo_qty, route=stage_list)

        created_routes = []
        for seq, stg in enumerate(stage_list, start=1):
            is_first = (seq == 1)
            tgt = targets.get(stg, wo.physical_wo_qty)
            r = WORoute(
                work_order_id=wo.id,
                stage=stg,
                sequence=seq,
                stage_target_qty=tgt,
                cumulative_ent_qty=wo.physical_wo_qty if is_first else 0,
                cumulative_ok_qty=0,
                cumulative_rej_qty=0,
                cumulative_inproc_qty=wo.physical_wo_qty if is_first else 0,
                cumulative_onhand_qty=0,
                stage_status="In-Progress" if is_first else "Pending"
            )
            db.add(r)
            created_routes.append(r)

            wip = StageWIP(
                work_order_id=wo.id,
                stage=stg,
                ent_qty=wo.physical_wo_qty if is_first else 0,
                ok_qty=0,
                inproc_qty=wo.physical_wo_qty if is_first else 0,
                onhand_qty=0,
                rejected_qty=0,
                available_wip=wo.physical_wo_qty if is_first else 0
            )
            db.add(wip)

        wo.current_stage = stage_list[0]
        wo.status = WOStatus.IN_PRODUCTION
        db.flush()
        return created_routes

    @staticmethod
    def reconcile_all_work_orders(db: Session) -> PlantReconciliationResponse:
        """
        Performs full plant-wide quantity reconciliation across all Work Orders.
        """
        wos = db.query(WorkOrder).all()
        recs = [OMSIntegrationService.reconcile_work_order(db, w) for w in wos]
        
        tot_rel = sum(r.released_qty for r in recs)
        tot_wip = sum(r.total_wip for r in recs)
        tot_rej = sum(r.total_rejected for r in recs)
        tot_disp = sum(r.dispatched_qty for r in recs)
        balanced_count = sum(1 for r in recs if r.is_balanced)
        mismatched_count = len(recs) - balanced_count

        return PlantReconciliationResponse(
            total_work_orders=len(recs),
            balanced_work_orders=balanced_count,
            mismatched_work_orders=mismatched_count,
            total_released_qty=tot_rel,
            total_wip_qty=tot_wip,
            total_rejected_qty=tot_rej,
            total_dispatched_qty=tot_disp,
            reconciliations=recs,
            is_plant_balanced=(mismatched_count == 0)
        )

    @staticmethod
    def link_wo_to_oar(db: Session, rows: List[WOOarLinkRow]) -> LinkResult:
        return link_wo_to_oar(db, rows)


def _normalize_code(val: Optional[str]) -> str:
    if not val:
        return ""
    s = str(val).strip().upper()
    return re.sub(r"\s*-\s*", "-", s)


def _parse_delivery_date(val: Optional[Union[date, datetime, str]]) -> Optional[date]:
    if not val:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    if not s or s.lower() in ("none", "null", "nan"):
        return None
    date_part = s.split()[0].split("T")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_part, fmt).date()
        except ValueError:
            pass
    return None


def _record_exception(db: Session, exc_type: str, detail: str, wo_id: Optional[str] = None):
    try:
        exc = OMSException(
            exception_type=exc_type,
            detail=detail,
            wo_id=wo_id
        )
        db.add(exc)
        db.flush()
    except Exception:
        pass
    try:
        audit = AuditLog(
            user_name="system:wo-oar-link",
            action="LINK_EXCEPTION",
            entity="WorkOrder" if wo_id else "OAR",
            entity_id=wo_id,
            new_value=exc_type,
            details=detail
        )
        db.add(audit)
        db.flush()
    except Exception:
        pass


def next_oar_sequence(db: Session) -> str:
    """Collision-free next OAR sequence generator."""
    pattern = re.compile(r"^OAR-(\d+)$", re.IGNORECASE)
    highest = 0
    for (oar_num,) in db.query(Order.oar_number).filter(Order.oar_number.isnot(None)).all():
        if oar_num:
            m = pattern.match(oar_num.strip())
            if m:
                try:
                    highest = max(highest, int(m.group(1)))
                except ValueError:
                    pass
    if highest == 0:
        count = db.query(Order).count()
        return f"OAR-{count + 1:04d}"
    return f"OAR-{highest + 1:04d}"


def _find_or_create_customer(db: Session, cust_str: str) -> Customer:
    cleaned = cust_str.strip()
    cust = db.query(Customer).filter(
        or_(
            func.lower(Customer.name) == cleaned.lower(),
            func.lower(Customer.customer_code) == cleaned.lower()
        )
    ).first()
    if cust:
        return cust
    norm_input = re.sub(r"[^a-zA-Z0-9]", "", cleaned).lower()
    for c in db.query(Customer).all():
        if (
            re.sub(r"[^a-zA-Z0-9]", "", c.name).lower() == norm_input
            or re.sub(r"[^a-zA-Z0-9]", "", c.customer_code).lower() == norm_input
        ):
            return c
    prefix = re.sub(r"[^A-Za-z]", "", cleaned)[:4].upper() or "CUST"
    code = prefix
    counter = 1
    while db.query(Customer).filter(Customer.customer_code == code).first():
        code = f"{prefix[:3]}{counter}"
        counter += 1
    cust = Customer(customer_code=code, name=cleaned, is_active=True)
    db.add(cust)
    db.flush()
    return cust


def _find_or_create_part(db: Session, part_no_str: str, grade: Optional[str] = None) -> Part:
    cleaned = part_no_str.strip()
    part = db.query(Part).filter(
        func.lower(Part.part_number) == cleaned.lower()
    ).first()
    if part:
        return part
    norm_input = re.sub(r"[^a-zA-Z0-9]", "", cleaned).lower()
    for p in db.query(Part).all():
        if re.sub(r"[^a-zA-Z0-9]", "", p.part_number).lower() == norm_input:
            return p
    part = Part(
        part_number=cleaned,
        grade=grade or "Standard",
        description=f"Component {cleaned}"
    )
    db.add(part)
    db.flush()
    return part


def link_wo_to_oar(db: Session, rows: List[WOOarLinkRow]) -> LinkResult:
    """
    Links team-assigned Work Order IDs to OARs (Orders) idempotently.
    Creates the OAR (= accepting a PO) only when one doesn't already exist for that order.
    Executes in a single DB transaction per row so one invalid row does not abort the batch.
    """
    result = LinkResult(
        total_processed=len(rows),
        linked_count=0,
        already_linked_count=0,
        created_oars_count=0,
        exceptions_count=0
    )

    for row in rows:
        try:
            # 1. SKIP IF ALREADY LINKED
            # If WorkOrder.query.filter_by(wo_id=row.wo_id).first() exists -> record as "already_linked", continue.
            norm_wo = _normalize_code(row.wo_id)
            existing_wo = db.query(WorkOrder).filter(
                or_(
                    WorkOrder.wo_number == row.wo_id.strip(),
                    WorkOrder.wo_number == norm_wo
                )
            ).first()

            if existing_wo:
                result.already_linked.append(row.wo_id)
                result.items.append(LinkResultItem(
                    wo_id=row.wo_id,
                    oar_no=existing_wo.order.oar_number if existing_wo.order else None,
                    status="already_linked",
                    detail="Work Order already exists in software"
                ))
                continue

            # 2. REQUIRED FIELDS
            # If any of customer_po_number, part_no, customer, wo_quantity is missing/blank,
            # or wo_quantity <= 0 -> insert into Exceptions table, continue.
            missing_fields = []
            if not row.customer_po_number or not str(row.customer_po_number).strip():
                missing_fields.append("customer_po_number")
            if not row.part_no or not str(row.part_no).strip():
                missing_fields.append("part_no")
            if not row.customer or not str(row.customer).strip():
                missing_fields.append("customer")
            if row.wo_quantity is None or row.wo_quantity <= 0:
                missing_fields.append(f"wo_quantity (got {row.wo_quantity})")

            if missing_fields:
                detail = f"WO {row.wo_id}: missing or invalid required field(s): {', '.join(missing_fields)}"
                _record_exception(db, "missing_field", detail, row.wo_id)
                db.commit()
                result.exceptions.append(LinkException(type="missing_field", detail=detail, wo_id=row.wo_id))
                result.items.append(LinkResultItem(wo_id=row.wo_id, oar_no=None, status="exception", detail=detail))
                continue

            # Resolve Customer and Part
            cust = _find_or_create_customer(db, row.customer)
            part = _find_or_create_part(db, row.part_no, grade=row.grade)

            # 3. FIND OR CREATE THE OAR — idempotent on (customer_po_number, part_no).
            # This is the 'one accepted order = one OAR' rule.
            clean_po = row.customer_po_number.strip()
            clean_part_no = row.part_no.strip()

            existing_oar = db.query(Order).join(Part).filter(
                func.lower(func.trim(Order.customer_po)) == clean_po.lower(),
                func.lower(func.trim(Part.part_number)) == clean_part_no.lower()
            ).first()

            if not existing_oar:
                existing_oar = db.query(Order).filter(
                    Order.part_id == part.id,
                    func.lower(func.trim(Order.customer_po)) == clean_po.lower()
                ).first()

            oar = None
            if existing_oar:
                # CASE A — existing_oar found:
                # If row.oar_no and row.oar_no != existing_oar.oar_no:
                # insert Exceptions(type="oar_mismatch", detail=f"WO {row.wo_id}: input says {row.oar_no}, DB has {existing_oar.oar_no}")
                # proceed using existing_oar.oar_no — DB is source of truth
                if row.oar_no and row.oar_no.strip():
                    norm_row_oar = _normalize_code(row.oar_no)
                    norm_db_oar = _normalize_code(existing_oar.oar_number)
                    if norm_row_oar != norm_db_oar:
                        detail = f"WO {row.wo_id}: input says {row.oar_no}, DB has {existing_oar.oar_number}"
                        _record_exception(db, "oar_mismatch", detail, row.wo_id)
                        result.exceptions.append(LinkException(type="oar_mismatch", detail=detail, wo_id=row.wo_id))

                # If existing_oar.customer.lower() != row.customer.lower():
                # insert Exceptions(type="customer_mismatch", detail=f"WO {row.wo_id}: OAR {existing_oar.oar_no}")
                # continue
                existing_cust_name = existing_oar.customer.name.strip().lower() if existing_oar.customer else ""
                existing_cust_code = existing_oar.customer.customer_code.strip().lower() if existing_oar.customer else ""
                input_cust = row.customer.strip().lower()

                cust_matched = (
                    input_cust == existing_cust_name
                    or input_cust == existing_cust_code
                    or input_cust in existing_cust_name
                    or existing_cust_name in input_cust
                    or re.sub(r"[^a-zA-Z0-9]", "", input_cust) == re.sub(r"[^a-zA-Z0-9]", "", existing_cust_name)
                )

                if not cust_matched:
                    detail = f"WO {row.wo_id}: OAR {existing_oar.oar_number} customer mismatch (input says '{row.customer}', DB has '{existing_oar.customer.name if existing_oar.customer else ''}')"
                    _record_exception(db, "customer_mismatch", detail, row.wo_id)
                    db.commit()
                    result.exceptions.append(LinkException(type="customer_mismatch", detail=detail, wo_id=row.wo_id))
                    result.items.append(LinkResultItem(wo_id=row.wo_id, oar_no=existing_oar.oar_number, status="exception", detail=detail))
                    continue

                oar = existing_oar
                # do NOT create a new OAR row, do NOT modify oar.po_quantity
            else:
                # CASE B — no existing_oar (genuinely new order):
                if row.oar_no and row.oar_no.strip():
                    cand_oar = _normalize_code(row.oar_no)
                    if not db.query(Order).filter(Order.oar_number == cand_oar).first():
                        oar_num = cand_oar
                    else:
                        oar_num = next_oar_sequence(db)
                else:
                    oar_num = next_oar_sequence(db)

                deliv_date = _parse_delivery_date(row.cust_delivery_date)
                po_qty = row.po_quantity if (row.po_quantity and row.po_quantity > 0) else row.wo_quantity

                oar = Order(
                    oar_number=oar_num,
                    customer_id=cust.id,
                    part_id=part.id,
                    customer_po=clean_po,
                    po_qty=po_qty,
                    max_batch_size=500,
                    delivery_date=deliv_date or date.today(),
                    order_type="Standard",
                    status=OrderStatus.ACCEPT,
                    source_type="schedule" if "SCH" in clean_po.upper() else "po"
                )
                db.add(oar)
                db.flush()
                result.created_oars.append(oar.oar_number)

                db.add(AuditLog(
                    user_name="system:wo-oar-link",
                    action="OAR_CREATE",
                    entity="Order",
                    entity_id=oar.oar_number,
                    new_value=f"PO: {clean_po}, Qty: {po_qty}",
                    details=f"via WO-OAR link, WO {row.wo_id}"
                ))

            # 4. CREATE THE WO (team-assigned ID — never auto-generate it here; this input's WO IDs are authoritative)
            wo = WorkOrder(
                wo_number=row.wo_id.strip(),
                order_id=oar.id,
                physical_wo_qty=row.wo_quantity,
                current_stage="F1",
                projected_final_good=row.wo_quantity,
                shortfall="No",
                status=WOStatus.IN_PRODUCTION,
                casting_process="CENTRIFUGAL"
            )
            db.add(wo)
            db.flush()

            # Initialize 7-stage routes and StageWIP
            OMSIntegrationService.initialize_wo_stages(db, wo)

            # Audit log
            db.add(AuditLog(
                user_name="system:wo-oar-link",
                action="WO_CREATE",
                entity="WorkOrder",
                entity_id=wo.wo_number,
                new_value=f"Qty: {row.wo_quantity}, OAR: {oar.oar_number}",
                details=f"Linked to OAR {oar.oar_number} for PO {clean_po}"
            ))

            db.commit()
            result.linked.append(wo.wo_number)
            result.items.append(LinkResultItem(
                wo_id=wo.wo_number,
                oar_no=oar.oar_number,
                status="linked",
                detail=f"Linked to OAR {oar.oar_number}"
            ))

        except Exception as e:
            db.rollback()
            detail = f"WO {row.wo_id}: unexpected failure: {str(e)}"
            _record_exception(db, "system_error", detail, row.wo_id)
            try:
                db.commit()
            except Exception:
                db.rollback()
            result.exceptions.append(LinkException(type="system_error", detail=detail, wo_id=row.wo_id))
            result.items.append(LinkResultItem(wo_id=row.wo_id, oar_no=None, status="exception", detail=detail))

    result.linked_count = len(result.linked)
    result.already_linked_count = len(result.already_linked)
    result.created_oars_count = len(result.created_oars)
    result.exceptions_count = len(result.exceptions)
    return result

