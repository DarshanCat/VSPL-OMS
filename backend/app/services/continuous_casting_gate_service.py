"""Continuous Casting <-> OMS material gate (Phase 10): a read-only validation boundary.

A Work Order whose ACTIVE routing is CONTINUOUS_CASTING bypasses F1: it enters production at the first stage
of its own released WORoute, and that stage may not produce more than the blanks that real, reconciled cutting
has actually delivered. The gate is called from exactly two existing OMS paths, after the WO lock and the
StageWIP lock and BEFORE any mutation of that request:

  ProductionService.record_stage_production   (stage == the WO's first route stage)
  ProductionService.move_parts                (moving OUT of the WO's first route stage, which can create
                                               first-stage production implicitly)

  usable_good_blanks = SUM(actual_good_blanks) of RECONCILED cut records whose allocation belongs to the
                       ACTIVE routing, whose work order is this WO, and whose CUT_CONSUME ledger row really
                       exists with the same allocation, unit and consumed length.
  rule               : existing first-stage (good + rejected) + this request's good + rejected
                       <= usable_good_blanks

Never counted: planned blanks, reserved / issued quantity, raw remaining length, consumed length converted
to pieces, client-supplied cumulative values, cut records of another WO or routing, of a DRAFT or SUPERSEDED
routing, or any cut result that is not RECONCILED. Rejected blanks are not usable OMS good pieces.

A WO with no China routing, or with an F1_PRODUCTION routing, is never touched. The gate takes no China
locks and writes nothing; StageWIP semantics, WORoute and the OMS engine are unchanged.
"""
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.continuous_casting import (
    ContinuousCastingAllocation, ContinuousCastingCutRecord, ContinuousCastingRouting,
    ContinuousCastingStockLedger, MATERIAL_SOURCE_CONTINUOUS_CASTING,
)

Cut, Ledger, Alloc, Routing = (ContinuousCastingCutRecord, ContinuousCastingStockLedger,
                               ContinuousCastingAllocation, ContinuousCastingRouting)
FIRST_STAGE_F1 = "F1"


def _reject(db: Session, detail: str):
    """Raise the gate's 400 after discarding this request's uncommitted work. The gate itself writes nothing,
    but the existing OMS paths may already have flushed rows for this request (move_parts initialises missing
    destination StageWIP rows before it validates); a rejected gate must leave NOTHING behind. Both call sites
    run it first thing after their locks, with nothing of the caller's own pending, so the rollback only
    discards what this request created."""
    db.rollback()
    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail)


class ContinuousCastingGateService:
    @staticmethod
    def active_china_routing(db: Session, wo):
        """The WO's ACTIVE CONTINUOUS_CASTING routing, or None (no China routing, a DRAFT / SUPERSEDED one,
        or an F1_PRODUCTION routing all mean: not gated)."""
        return db.query(Routing).filter(
            Routing.work_order_id == wo.id, Routing.status == "ACTIVE",
            Routing.material_source == MATERIAL_SOURCE_CONTINUOUS_CASTING).first()

    @staticmethod
    def usable_good_blanks(db: Session, wo, routing) -> int:
        """Good blanks the OMS may consume, derived only from authoritative, reconciled China records."""
        total = db.query(func.coalesce(func.sum(Cut.actual_good_blanks), 0)).select_from(Cut).join(
            Ledger, Ledger.id == Cut.ledger_entry_id).join(Alloc, Alloc.id == Cut.allocation_id).filter(
            Cut.work_order_id == wo.id,
            Alloc.routing_id == routing.id,
            Cut.reconciliation_status == "RECONCILED",
            Cut.variance_mm == 0,
            Ledger.movement_type == "CUT_CONSUME",
            Ledger.allocation_id == Cut.allocation_id,
            Ledger.stock_unit_id == Cut.stock_unit_id,
            Ledger.length_mm == Cut.consumed_length_mm,
        ).scalar()
        return int(total or 0)

    @staticmethod
    def enforce_first_stage_production(db: Session, wo, routes, stage: str, existing_consumed: int,
                                       additional_quantity: int) -> None:
        """Reject (HTTP 400, before any mutation) first-stage production the China material cannot cover.

        `routes` is the WO's own WORoute rows in sequence order; `stage` the stage being produced or moved
        out of; `existing_consumed` the authoritative StageWIP good + rejected already at that stage;
        `additional_quantity` this request's own first-stage production (good + rejected) as already
        computed by the existing OMS logic."""
        is_continuous_wo = getattr(wo, "casting_process", None) == "CONTINUOUS"
        routing = ContinuousCastingGateService.active_china_routing(db, wo)

        # 1. Continuous Casting bypasses F1 production
        if is_continuous_wo and stage.strip().upper() == FIRST_STAGE_F1:
            _reject(
                db, f"Work Order '{wo.wo_number}' uses Continuous Casting, which bypasses F1. "
                f"Use the Continuous Casting workflow (Planning -> Allocation -> Cutting) to produce blanks before downstream production.")

        # 2. Continuous Casting WO requires an active CC routing before shop-floor production
        if is_continuous_wo and routing is None:
            _reject(
                db, f"Work Order '{wo.wo_number}' is marked for Continuous Casting but has no active Continuous Casting routing. "
                f"Create and activate a routing in Continuous Casting Planning before production.")

        if routing is None or not routes:
            return                                              # F1 / no China routing: completely unchanged
        first_stage = routes[0].stage
        if stage != first_stage:
            return                                              # only the first stage consumes China blanks
        if first_stage.strip().upper() == FIRST_STAGE_F1:
            _reject(
                db, f"Work Order '{wo.wo_number}' uses continuous-casting stock, which bypasses F1, but its released "
                f"route still starts at F1; it cannot produce at F1. Release it with its first downstream stage "
                f"as the first route stage.")
        if additional_quantity <= 0:
            return                                              # nothing new is produced by this request
        usable = ContinuousCastingGateService.usable_good_blanks(db, wo, routing)
        if existing_consumed + additional_quantity > usable:
            _reject(
                db, f"Continuous-casting material gate: stage '{first_stage}' of Work Order '{wo.wo_number}' has "
                f"{existing_consumed} good/rejected piece(s) already and this request adds {additional_quantity}, "
                f"but only {usable} usable good blank(s) are available from reconciled cut results of routing "
                f"v{routing.version}.")
