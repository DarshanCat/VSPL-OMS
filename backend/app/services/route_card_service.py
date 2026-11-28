"""Route card (docs/route-card-architecture.md).

Builds the printable route card of one work order from data OMS already holds. It is READ ONLY:
nothing is written, no quantity, WIP, MRB or vendor record is changed, and nothing is stored.
The card is drawn live every time it is asked for, so a reprint always shows today's dates and
quantities.

Phase 1 rows are the gates on the work order's route. Process steps inside a gate, roles and the
Part Master extras (die from DMS, bin, cost, bath no) arrive in later phases; their cells are
returned empty so the card layout does not change when they are added.
"""
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.mrb import MRBReview
from app.models.production_movement import StageWIP
from app.models.setup_planning import PlanningSetup, WOHeat
from app.models.vendor import VendorDispatch
from app.models.work_order import WorkOrder, WORoute

DOC_NUMBER = "VSPL-PPC-F-04"
DOC_REV_DATE = "2022-02-16"

GATE_LABELS = {
    "F1": "Casting Approval (F1)",
    "F2": "Stage Approval (F2)",
    "F3": "Stage Approval (F3)",
    "SP": "Special Process (SP)",
    "FI": "Final Inspection (FI)",
    "PACKING": "Packing",
    "BSR": "BSR",
    "DISPATCH": "Dispatch",
}
# Dispatch has its own flow and is not printed on the card.
HIDDEN_GATES = {"DISPATCH"}
ACTIVE_TRIP_STATUSES = ("AT_VENDOR", "PARTIALLY_RECEIVED")


def _find_wo(db: Session, wo_identifier: str) -> Optional[WorkOrder]:
    ident = (wo_identifier or "").strip()
    if not ident:
        return None
    wo = db.query(WorkOrder).filter(WorkOrder.wo_number == ident).first()
    if wo is None:
        try:
            wo = db.query(WorkOrder).filter(WorkOrder.id == uuid.UUID(ident)).first()
        except ValueError:
            wo = None
    return wo


def _iso(d: Any) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date().isoformat()
    return d.isoformat() if isinstance(d, date) else str(d)


def _wo_type(wo: WorkOrder) -> str:
    if getattr(wo, "is_replacement", False):
        return "Replacement"
    if (getattr(wo, "classification", None) or "").strip().lower() == "npd":
        return "NPD"
    return "Regular"


def _gate_quantities(db: Session, wo: WorkOrder, stage: str, wip: Optional[StageWIP]) -> Dict[str, Any]:
    """Production / accepted / rejected for one gate.

    Quantities are taken from the Material Review Board: production = what the floor reported,
    accepted and rejected = what MRB has approved (verified quantities win over reported ones).
    Quantities still waiting in MRB are returned as `pending_qty`. A gate with no MRB ticket (for
    example Final Inspection, which does not need MRB) falls back to the recorded gate quantities.
    """
    tickets = db.query(MRBReview).filter(
        MRBReview.work_order_id == wo.id, MRBReview.stage == stage.strip().upper()
    ).all()
    if not tickets:
        ok = int(wip.ok_qty or 0) if wip else 0
        rej = int(wip.rejected_qty or 0) if wip else 0
        recorded = ok + rej
        return {"production_qty": recorded, "accepted_qty": ok, "rejected_qty": rej,
                "pending_qty": 0, "quantity_source": "FLOOR" if recorded else "NONE"}

    live = [t for t in tickets if t.status != "REJECTED"]
    production = sum((t.reported_ok_qty or 0) + (t.reported_reject_qty or 0) for t in live)
    approved = [t for t in tickets if t.status in ("APPROVED", "ADJUSTED")]
    accepted = sum(t.verified_ok_qty if t.verified_ok_qty is not None else (t.reported_ok_qty or 0) for t in approved)
    rejected = sum(t.verified_reject_qty if t.verified_reject_qty is not None else (t.reported_reject_qty or 0) for t in approved)
    pending = sum((t.reported_ok_qty or 0) + (t.reported_reject_qty or 0) for t in tickets if t.status == "PENDING")
    return {"production_qty": production, "accepted_qty": accepted, "rejected_qty": rejected,
            "pending_qty": pending, "quantity_source": "MRB"}


def build_route_card(db: Session, wo_identifier: str) -> Optional[Dict[str, Any]]:
    # Imported here to reuse the one existing customer part number lookup without a module cycle.
    from app.services.work_order_service import (
        compute_wo_release_status, get_wo_oar_allocations, resolve_order_customer_part_number,
    )

    wo = _find_wo(db, wo_identifier)
    if wo is None:
        return None

    order = wo.order
    customer = order.customer if order is not None else None
    part = order.part if order is not None else None

    # --- PO numbers (a merged work order lists every OAR / PO it serves) -----------------------
    allocs = get_wo_oar_allocations(db, wo)
    pos: List[str] = []
    oars: List[str] = []
    if len(allocs) > 1:
        for a in allocs:
            if a.order is not None:
                if a.order.customer_po and a.order.customer_po not in pos:
                    pos.append(a.order.customer_po)
                if a.order.oar_number and a.order.oar_number not in oars:
                    oars.append(a.order.oar_number)
    elif order is not None:
        if order.customer_po:
            pos.append(order.customer_po)
        if order.oar_number:
            oars.append(order.oar_number)

    # --- Heats and setup -----------------------------------------------------------------------
    heats = [h.heat_number for h in db.query(WOHeat).filter(WOHeat.work_order_id == wo.id)
             .order_by(WOHeat.added_at.asc()).all() if h.heat_number]
    if not heats and wo.heat_number:
        heats = [wo.heat_number]
    setup_number = None
    if wo.setup_id:
        setup = db.query(PlanningSetup).filter(PlanningSetup.id == wo.setup_id).first()
        setup_number = setup.setup_number if setup else None

    # --- Gate rows -----------------------------------------------------------------------------
    routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
    wips = {w.stage: w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
    trips = db.query(VendorDispatch).filter(
        VendorDispatch.work_order_id == wo.id, VendorDispatch.cancelled_at.is_(None)
    ).order_by(VendorDispatch.dispatched_at.asc()).all()

    rows: List[Dict[str, Any]] = []
    for r in routes:
        gate = (r.stage or "").strip().upper()
        if gate in HIDDEN_GATES:
            continue
        gate_trips = [t for t in trips if (t.dispatch_stage or "").strip().upper() == gate]
        vendor_trips = [{
            "vendor_name": t.vendor_name,
            "dc_number": t.dc_number,
            "process_name": t.process_name,
            "sent_qty": int(t.dispatched_qty or 0),
            "out_qty": max(int(t.dispatched_qty or 0) - int(t.received_qty or 0) - int(t.scrap_qty or 0), 0)
            if t.status in ACTIVE_TRIP_STATUSES else 0,
            "status": t.status,
        } for t in gate_trips]
        qty = _gate_quantities(db, wo, gate, wips.get(r.stage))
        rows.append({
            "gate": gate,
            "sequence": r.sequence,
            "process": GATE_LABELS.get(gate, gate),
            "start_date": _iso(r.planned_start),
            "end_date": _iso(r.planned_end),
            "responsibility": None,           # roles arrive with the organisation chart (phase 2)
            "part_route": "VENDOR" if vendor_trips else "IN_HOUSE",
            "vendor_trips": vendor_trips,
            "qty_out_at_vendor": sum(v["out_qty"] for v in vendor_trips),
            **qty,
        })

    released = compute_wo_release_status(wo) == "RELEASED"
    return {
        "doc_number": DOC_NUMBER,
        "doc_rev_date": DOC_REV_DATE,
        "issue_date": date.today().isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "revision": int(wo.plan_version or 0),
        "is_draft": not released,
        "release_status": compute_wo_release_status(wo),
        "wo_number": wo.wo_number,
        "wo_type": _wo_type(wo),
        "source_wo_number": wo.source_wo.wo_number if getattr(wo, "source_wo", None) else None,
        "customer_name": customer.name if customer is not None else None,
        "customer_code": customer.customer_code if customer is not None else None,
        "po_numbers": pos,
        "oar_numbers": oars,
        "internal_part_number": part.part_number if part is not None else None,
        "unique_production_code": part.part_number if part is not None else None,
        "customer_part_number": resolve_order_customer_part_number(db, order),
        "tool_assembly_description": part.description if part is not None else None,
        "internal_grade": part.grade if part is not None else None,
        "fg_qty": int(order.po_qty) if order is not None and order.po_qty is not None else int(wo.physical_wo_qty or 0),
        "rc_qty": int(wo.physical_wo_qty or 0) if released else None,
        "wo_qty": int(wo.physical_wo_qty or 0),
        "heat_numbers": heats,
        "setup_number": setup_number,
        "casting_process": wo.casting_process,
        # Not stored in OMS yet: die ID comes from DMS later, bin / M/C cost / bath no arrive with
        # the planning module and the Part Master extras. Printed as empty boxes.
        "die_id": None, "machine_cost": None, "bin_id": None, "bath_no": None,
        "gates": rows,
    }
