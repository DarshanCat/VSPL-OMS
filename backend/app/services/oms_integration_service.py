import math
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.nc import NCRecord
from app.schemas.production import ReconciliationItem, PlantReconciliationResponse

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
