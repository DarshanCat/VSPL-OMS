"""Continuous Casting cut RESULT recording (Phase 10).

CUT_CONSUME (Phase 6) records only how many millimetres left the stock; it knows nothing about blanks.
This operation records what that real cut actually produced -- good blanks, rejected blanks, saw cuts and
end trim -- as an immutable cc_cut_records row tied to exactly one existing CUT_CONSUME ledger transaction.
It writes no ledger row, changes no stock balance and creates no second CUT_CONSUME.

Validation (all server-side; no cumulative figure is accepted from the client):
  * the ledger transaction exists, is a CUT_CONSUME, and belongs to the stated allocation and stock unit;
    the allocation belongs to the stated routing and unit; the routing is a CONTINUOUS_CASTING routing that
    is ACTIVE or SUPERSEDED (a cut made before a supersession can still be recorded);
  * consumed_length_mm equals the ledger row's length exactly;
  * the routing's OWN cutting formula (calculate_gross_required_length_mm):
        required = (good + rejected) x blank_length + actual_cuts x kerf + end_trim
    with blank_length and kerf taken from the routing. consumed < required is rejected (the blanks cannot
    be longer than the material consumed); consumed == required is RECONCILED, variance 0; consumed >
    required is stored as VARIANCE with variance_mm = consumed - required (unexplained consumption). Only
    a RECONCILED result of an ACTIVE routing is usable by the OMS gate. No millimetre is rounded;
  * good + rejected blanks recorded across the whole routing may not exceed the routing's planned_blanks.

One result per CUT_CONSUME ledger row (a unique index). An optional client_request_id replays safely: the
same key and the same request returns the original; the same key for a different request is a 409.
Locks, in the established order: StockUnit -> Allocation -> Routing (the routing lock also serialises the
cumulative planned-blank check). A VARIANCE result is permanent (the record is immutable); a resolution
workflow is not part of Phase 10.
"""
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.roles import CC_CUT_ROLES
from app.models.audit import AuditLog
from app.models.user import User
from app.models.work_order import WorkOrder
from app.models.continuous_casting import (
    ContinuousCastingAllocation, ContinuousCastingCutRecord, ContinuousCastingStockLedger,
    MATERIAL_SOURCE_CONTINUOUS_CASTING, next_cc_cut_number,
)
from app.schemas.continuous_casting import CCCutResultCreate, CCCutResultResult
from app.services.continuous_casting_service import _require_role, _bad_request
from app.services.continuous_casting_routing_service import calculate_gross_required_length_mm
from app.services.continuous_casting_reservation_service import _acquire, _run, ROUTING_ACTIVE, ROUTING_SUPERSEDED

Cut, Ledger, Alloc = ContinuousCastingCutRecord, ContinuousCastingStockLedger, ContinuousCastingAllocation
RECONCILED = "RECONCILED"
VARIANCE = "VARIANCE"
CUT_CONSUME = "CUT_CONSUME"


def _fingerprint(req: CCCutResultCreate) -> tuple:
    return (req.routing_id, req.allocation_id, req.stock_unit_id, req.ledger_transaction_number.strip(),
            req.consumed_length_mm, req.actual_good_blanks, req.rejected_blanks, req.actual_cuts, req.end_trim_mm)


def _record_fingerprint(rec: Cut, routing_id, ledger_txn: str) -> tuple:
    return (routing_id, rec.allocation_id, rec.stock_unit_id, ledger_txn, rec.consumed_length_mm,
            rec.actual_good_blanks, rec.rejected_blanks, rec.actual_cuts, rec.end_trim_mm)


def _result(rec: Cut, wo_number, routing, allocation, unit_number, ledger_txn, required, recorded, replayed, message):
    return CCCutResultResult(
        success=True, replayed=replayed, cut_number=rec.cut_number, wo_number=wo_number,
        routing_id=str(routing.id), routing_version=routing.version, routing_status=routing.status,
        allocation_number=allocation.allocation_number, stock_unit_number=unit_number,
        ledger_transaction_number=ledger_txn, planned_blanks=rec.planned_blanks,
        actual_good_blanks=rec.actual_good_blanks, rejected_blanks=rec.rejected_blanks, actual_cuts=rec.actual_cuts,
        blank_length_mm=rec.blank_length_mm, kerf_mm=rec.kerf_mm, end_trim_mm=rec.end_trim_mm,
        consumed_length_mm=rec.consumed_length_mm, required_length_mm=required, variance_mm=rec.variance_mm,
        reconciliation_status=rec.reconciliation_status,
        usable_for_oms=rec.reconciliation_status == RECONCILED and routing.status == ROUTING_ACTIVE,
        routing_blanks_recorded=recorded, routing_planned_blanks=routing.planned_blanks, message=message,
    )


def _recorded_blanks(db: Session, routing_id) -> int:
    return int(db.query(func.coalesce(func.sum(Cut.actual_good_blanks + Cut.rejected_blanks), 0)).select_from(
        Cut).join(Alloc, Alloc.id == Cut.allocation_id).filter(Alloc.routing_id == routing_id).scalar())


def _record(db: Session, req: CCCutResultCreate, current_user: User) -> CCCutResultResult:
    txn = req.ledger_transaction_number.strip() if isinstance(req.ledger_transaction_number, str) else ""
    if not txn:
        raise _bad_request("ledger_transaction_number is required.")
    for name in ("consumed_length_mm", "actual_good_blanks", "rejected_blanks", "actual_cuts", "end_trim_mm"):
        value = getattr(req, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _bad_request(f"{name} must be a whole number, never negative.")
    if req.consumed_length_mm <= 0:
        raise _bad_request("consumed_length_mm must be positive.")
    blanks = req.actual_good_blanks + req.rejected_blanks
    if blanks <= 0:
        raise _bad_request("A cut result must record at least one good or rejected blank.")
    key = req.client_request_id.strip() if isinstance(req.client_request_id, str) and req.client_request_id.strip() else None

    allocation, unit, routing = _acquire(db, req.allocation_id)           # StockUnit -> Allocation -> Routing
    wo = db.query(WorkOrder).filter(WorkOrder.id == routing.work_order_id).first()
    if wo is None:
        raise _bad_request("The routing's Work Order is missing.")

    if key is not None:
        prior = db.query(Cut).filter(Cut.client_request_id == key).first()
        if prior is not None:
            prior_ledger = db.query(Ledger).filter(Ledger.id == prior.ledger_entry_id).first()
            prior_txn = prior_ledger.transaction_number if prior_ledger else ""
            prior_alloc = db.query(Alloc).filter(Alloc.id == prior.allocation_id).first()
            if (prior_alloc is not None and prior_alloc.routing_id == req.routing_id
                    and _fingerprint(req) == _record_fingerprint(prior, req.routing_id, prior_txn)):
                required = calculate_gross_required_length_mm(
                    prior.actual_good_blanks + prior.rejected_blanks, prior.blank_length_mm, prior.actual_cuts,
                    prior.kerf_mm, prior.end_trim_mm)
                return _result(prior, wo.wo_number, routing, allocation, unit.unit_number, prior_txn, required,
                               _recorded_blanks(db, routing.id), True,
                               f"Cut result {prior.cut_number} was already recorded; nothing was repeated.")
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "client_request_id was already used for a different request; nothing was saved.")

    ledger = db.query(Ledger).filter(Ledger.transaction_number == txn).first()
    if ledger is None:
        raise _bad_request(f"Ledger transaction '{txn}' does not exist.")
    if ledger.movement_type != CUT_CONSUME:
        raise _bad_request(f"Ledger transaction '{txn}' is a {ledger.movement_type}, not a CUT_CONSUME.")
    if allocation.routing_id != req.routing_id:
        raise _bad_request(f"Allocation {allocation.allocation_number} does not belong to the routing supplied.")
    if allocation.stock_unit_id != req.stock_unit_id or unit.id != req.stock_unit_id:
        raise _bad_request(f"Stock unit supplied is not the unit allocated on {allocation.allocation_number}.")
    if ledger.allocation_id != allocation.id or ledger.stock_unit_id != unit.id:
        raise _bad_request(
            f"Ledger transaction '{txn}' was not a cut of allocation {allocation.allocation_number} on "
            f"{unit.unit_number}.")
    if routing.material_source != MATERIAL_SOURCE_CONTINUOUS_CASTING:
        raise _bad_request("Only a CONTINUOUS_CASTING routing can have a cut result.")
    if routing.status not in (ROUTING_ACTIVE, ROUTING_SUPERSEDED):
        raise _bad_request(f"Routing v{routing.version} is {routing.status}; a cut result needs an ACTIVE or "
                           f"SUPERSEDED routing.")
    if req.consumed_length_mm != ledger.length_mm:
        raise _bad_request(
            f"consumed_length_mm {req.consumed_length_mm} does not match the {ledger.length_mm} mm consumed by "
            f"ledger transaction '{txn}'.")
    if db.query(Cut.id).filter(Cut.ledger_entry_id == ledger.id).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A cut result is already recorded for ledger transaction '{txn}'; it is immutable.")

    try:
        required = calculate_gross_required_length_mm(
            blanks, routing.blank_length_mm, req.actual_cuts, routing.kerf_mm, req.end_trim_mm)
    except ValueError as exc:
        raise _bad_request(str(exc))
    variance = ledger.length_mm - required
    if variance < 0:
        raise _bad_request(
            f"The consumed {ledger.length_mm} mm cannot produce {blanks} blank(s) of {routing.blank_length_mm} mm "
            f"with {req.actual_cuts} cut(s) of {routing.kerf_mm} mm kerf and {req.end_trim_mm} mm end trim: "
            f"that needs {required} mm.")
    recorded = _recorded_blanks(db, routing.id)
    if recorded + blanks > routing.planned_blanks:
        raise _bad_request(
            f"Recording {blanks} blank(s) would take routing v{routing.version} to {recorded + blanks}, past its "
            f"{routing.planned_blanks} planned blank(s) ({recorded} already recorded).")

    actor = current_user.full_name
    status_value = RECONCILED if variance == 0 else VARIANCE
    rec = Cut(
        cut_number=next_cc_cut_number(db), work_order_id=wo.id, allocation_id=allocation.id, stock_unit_id=unit.id,
        ledger_entry_id=ledger.id, planned_blanks=routing.planned_blanks, actual_good_blanks=req.actual_good_blanks,
        rejected_blanks=req.rejected_blanks, blank_length_mm=routing.blank_length_mm, kerf_mm=routing.kerf_mm,
        actual_cuts=req.actual_cuts, end_trim_mm=req.end_trim_mm, consumed_length_mm=ledger.length_mm,
        retained_remnant_unit_id=None, retained_remnant_length_mm=0, reconciliation_status=status_value,
        variance_mm=variance, remarks=req.remarks, client_request_id=key,
        performed_by_id=current_user.id, performed_by_name=actor,
    )
    db.add(rec)
    db.add(AuditLog(
        user_id=current_user.id, user_name=actor, action="CC_CUT_RESULT", entity="ContinuousCastingCutRecord",
        entity_id=rec.cut_number,
        new_value=f"{req.actual_good_blanks} good / {req.rejected_blanks} rejected blanks from {txn}: {status_value}",
        details=f"{wo.wo_number} routing v{routing.version}, variance {variance} mm",
    ))
    db.flush()
    note = ("usable by the OMS gate" if status_value == RECONCILED and routing.status == ROUTING_ACTIVE
            else "NOT usable by the OMS gate" + (f" (variance {variance} mm)" if variance else ""))
    return _result(rec, wo.wo_number, routing, allocation, unit.unit_number, txn, required, recorded + blanks, False,
                   f"Cut result {rec.cut_number} recorded for {txn}: {status_value}; {note}.")


class ContinuousCastingCutService:
    @staticmethod
    def record_cut_result(db: Session, req: CCCutResultCreate, current_user: Optional[User] = None) -> CCCutResultResult:
        """Record the actual blanks produced by one real CUT_CONSUME. Immutable; no ledger row is written."""
        _require_role(current_user, CC_CUT_ROLES, "record a continuous-casting cut result")
        return _run(db, lambda: _record(db, req, current_user))
