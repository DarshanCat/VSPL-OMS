"""Continuous Casting SPLIT_OUT / SPLIT_IN (Phase 8): a retained remnant becomes a child unit.

A split moves FREE length from one stock unit to one new child unit. Nothing is consumed and no
length is created:

  parent  remaining - X ; reserved, issued, consumed, original unchanged
  child   NEW unit and UNIT number; original = remaining = X; reserved = issued = consumed = 0;
          parent_unit_id = parent; same inward (hence the same QA context); location inherited

Only free length (remaining - reserved - issued) can move, because reserved and issued length is
bound to allocations on the parent. So no allocation and no routing is touched, and none is locked:
the parent StockUnit lock (taken first, like every other operation) serialises a split against
RESERVE / ISSUE / CUT_CONSUME / RETURN on that unit. The child does not exist before the
transaction, so no second row lock is needed and parent/child cannot deadlock.

A split exhausting the parent is allowed only when the parent has already consumed length (the
"remnant of a cut" case): the parent is then CONSUMED (terminal, remaining 0, consumed > 0). A split
that would leave a parent with remaining 0 and consumed 0 is a pure rename of the bar and is rejected.
The piece count is not changed (split ledger rows carry no piece_qty; the inward's
received_piece_count is a receipt fact).

Two immutable ledger rows are written, SPLIT_OUT (on the parent) and SPLIT_IN (on the child), each
naming the other unit in related_stock_unit_id. Reconciliation then verifies, before commit, both
units' balances against the ledger (including remaining), the split pair, and the inward-level
conservation: sum(remaining + consumed) over the inward's units = the inward's received length.

NOTE: SQLite ignores FOR UPDATE; the lock REQUEST and the post-lock re-read are tested, but
PostgreSQL row-lock behaviour itself is not proven by SQLite. No client_request_id exists here.
"""
import uuid
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.roles import CC_ISSUE_ROLES
from app.models.audit import AuditLog
from app.models.user import User
from app.models.continuous_casting import (
    ContinuousCastingInward, ContinuousCastingStockUnit, ContinuousCastingStockLedger,
    UNIT_STATUS_IN_STOCK, allocation_ineligibility_reason, next_cc_unit_number,
    next_cc_ledger_transaction_numbers,
)
from app.schemas.continuous_casting import CCSplitCreate, CCSplitResult
from app.services.continuous_casting_service import _require_role, _bad_request
from app.services.continuous_casting_reservation_service import (
    _lock, _ledger_totals, _reconcile, _run, UNIT_STATUS_CONSUMED,
)

SPLIT_OUT = "SPLIT_OUT"
SPLIT_IN = "SPLIT_IN"
Unit, Ledger = ContinuousCastingStockUnit, ContinuousCastingStockLedger


def _fail(message: str):
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, message + "; nothing was changed.")


def _free(unit) -> int:
    return unit.remaining_length_mm - unit.reserved_length_mm - unit.issued_length_mm


def reconcile_inward(db: Session, inward: ContinuousCastingInward) -> int:
    """Inward-level conservation. Returns sum(remaining + consumed + scrapped) over every unit of the
    inward, which must equal received - sum(ADJUSTMENT_OUT) + sum(ADJUSTMENT_IN). The receipt length,
    the INWARD ledger rows and the root units' original lengths must all agree (the receipt is never
    rewritten), and SPLIT_OUT must equal SPLIT_IN (a split neither creates nor destroys length)."""
    rem, cons, scrapped = db.query(
        func.coalesce(func.sum(Unit.remaining_length_mm), 0), func.coalesce(func.sum(Unit.consumed_length_mm), 0),
        func.coalesce(func.sum(Unit.scrapped_length_mm), 0),
    ).filter(Unit.inward_id == inward.id).one()
    roots_original = db.query(func.coalesce(func.sum(Unit.original_length_mm), 0)).filter(
        Unit.inward_id == inward.id, Unit.parent_unit_id.is_(None)).scalar()
    totals = _ledger_totals(db, Ledger.inward_id == inward.id)
    held = int(rem) + int(cons) + int(scrapped)
    expected = inward.received_total_length_mm - totals.get("ADJUSTMENT_OUT", 0) + totals.get("ADJUSTMENT_IN", 0)
    if not (int(roots_original) == totals.get("INWARD", 0) == inward.received_total_length_mm):
        raise _fail(f"Inward {inward.inward_number} does not conserve length (root units {int(roots_original)} mm, "
                    f"ledger {totals.get('INWARD', 0)} mm, receipt {inward.received_total_length_mm} mm)")
    if held != expected:
        raise _fail(f"Inward {inward.inward_number} does not conserve length (units account for {held} mm, "
                    f"expected {expected} mm = receipt {inward.received_total_length_mm} mm - adjustments out "
                    f"{totals.get('ADJUSTMENT_OUT', 0)} mm + adjustments in {totals.get('ADJUSTMENT_IN', 0)} mm)")
    if totals.get(SPLIT_OUT, 0) != totals.get(SPLIT_IN, 0):
        raise _fail(f"Inward {inward.inward_number} SPLIT_OUT and SPLIT_IN lengths differ")
    return held


def _reconcile_split(db: Session, parent, child, length_mm: int) -> None:
    out_rows = db.query(Ledger).filter(
        Ledger.movement_type == SPLIT_OUT, Ledger.stock_unit_id == parent.id,
        Ledger.related_stock_unit_id == child.id).all()
    in_rows = db.query(Ledger).filter(
        Ledger.movement_type == SPLIT_IN, Ledger.stock_unit_id == child.id,
        Ledger.related_stock_unit_id == parent.id).all()
    if len(out_rows) != 1 or len(in_rows) != 1 or out_rows[0].length_mm != length_mm or in_rows[0].length_mm != length_mm:
        raise _fail(f"Split of {parent.unit_number} into {child.unit_number} does not have one matching SPLIT_OUT/SPLIT_IN pair")
    if out_rows[0].inward_id != in_rows[0].inward_id or child.inward_id != parent.inward_id:
        raise _fail(f"Split of {parent.unit_number} crosses inwards")
    if child.parent_unit_id != parent.id or child.original_length_mm != length_mm or child.remaining_length_mm != length_mm:
        raise _fail(f"Child {child.unit_number} does not match the split")
    split_out_total = _ledger_totals(db, Ledger.stock_unit_id == parent.id).get(SPLIT_OUT, 0)
    children_total = db.query(func.coalesce(func.sum(Unit.original_length_mm), 0)).filter(
        Unit.parent_unit_id == parent.id).scalar()
    if split_out_total != int(children_total):
        raise _fail(f"Unit {parent.unit_number} split-out length {split_out_total} mm differs from its children "
                    f"({int(children_total)} mm)")


def _split(db: Session, req: CCSplitCreate, current_user: User):
    length_mm = req.length_mm
    if req.stock_unit_id is None or req.inward_id is None:
        raise _bad_request("stock_unit_id and inward_id are required.")
    if isinstance(length_mm, bool) or not isinstance(length_mm, int) or length_mm <= 0:
        raise _bad_request("Length must be a positive whole number of millimetres.")

    parent = _lock(db, Unit, req.stock_unit_id)                      # the only row lock a split needs
    if parent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stock unit not found.")
    if parent.inward_id != req.inward_id:
        raise _bad_request(f"Inward supplied is not the inward of stock unit {parent.unit_number}.")
    if parent.status != UNIT_STATUS_IN_STOCK:
        raise _bad_request(
            f"Stock unit {parent.unit_number} is {parent.status}; only an {UNIT_STATUS_IN_STOCK} unit can be split.")
    free = _free(parent)
    if length_mm > free:
        raise _bad_request(
            f"Cannot split {length_mm} mm from {parent.unit_number}: only {max(free, 0)} mm is free "
            f"(reserved {parent.reserved_length_mm} mm and issued {parent.issued_length_mm} mm cannot be split off).")
    if length_mm == parent.remaining_length_mm and parent.consumed_length_mm == 0:
        raise _bad_request(
            f"Splitting all {length_mm} mm of {parent.unit_number} would only rename the bar; "
            f"a unit with nothing consumed must keep some length.")
    inward = db.query(ContinuousCastingInward).filter(
        ContinuousCastingInward.id == parent.inward_id).populate_existing().first()
    if inward is None:
        raise _bad_request("The unit's inward is missing.")

    actor = current_user.full_name
    child_number = next_cc_unit_number(db)
    out_txn, in_txn = next_cc_ledger_transaction_numbers(db, 2)
    reference = f"{parent.unit_number} -> {child_number}"

    parent.remaining_length_mm -= length_mm
    exhausted = parent.remaining_length_mm == 0
    if exhausted:
        parent.status = UNIT_STATUS_CONSUMED                         # only reachable with consumed > 0 (checked above)
    child = Unit(
        id=uuid.uuid4(), unit_number=child_number, inward_id=parent.inward_id, parent_unit_id=parent.id,
        original_length_mm=length_mm, remaining_length_mm=length_mm,
        reserved_length_mm=0, issued_length_mm=0, consumed_length_mm=0,
        status=UNIT_STATUS_IN_STOCK, location=parent.location, created_by=actor,
    )
    db.add(child)
    db.flush()
    reason = (req.reason.strip() if isinstance(req.reason, str) and req.reason.strip() else None)
    db.add(Ledger(
        transaction_number=out_txn, movement_type=SPLIT_OUT, inward_id=parent.inward_id,
        stock_unit_id=parent.id, related_stock_unit_id=child.id, allocation_id=None, length_mm=length_mm,
        piece_qty=None, unit_remaining_after_mm=parent.remaining_length_mm,
        reason=reason or f"Split {length_mm} mm out to {child_number}", reference=reference,
        performed_by_id=current_user.id, performed_by_name=actor,
    ))
    db.add(Ledger(
        transaction_number=in_txn, movement_type=SPLIT_IN, inward_id=parent.inward_id,
        stock_unit_id=child.id, related_stock_unit_id=parent.id, allocation_id=None, length_mm=length_mm,
        piece_qty=None, unit_remaining_after_mm=child.remaining_length_mm,
        reason=reason or f"Split {length_mm} mm in from {parent.unit_number}", reference=reference,
        performed_by_id=current_user.id, performed_by_name=actor,
    ))
    db.add(AuditLog(
        user_id=current_user.id, user_name=actor, action="CC_SPLIT", entity="ContinuousCastingStockUnit",
        entity_id=parent.unit_number,
        new_value=f"SPLIT {length_mm} mm {parent.unit_number} -> {child_number}",
        details=reason or f"Retained remnant {child_number}",
    ))
    db.flush()
    _reconcile(db, parent)
    _reconcile(db, child)
    _reconcile_split(db, parent, child, length_mm)
    held = reconcile_inward(db, inward)

    block = allocation_ineligibility_reason(child)
    return CCSplitResult(
        success=True, split_out_transaction_number=out_txn, split_in_transaction_number=in_txn,
        inward_id=str(inward.id), inward_number=inward.inward_number, length_mm=length_mm,
        parent_unit_id=str(parent.id), parent_unit_number=parent.unit_number, parent_status=parent.status,
        parent_remaining_length_mm=parent.remaining_length_mm, parent_reserved_length_mm=parent.reserved_length_mm,
        parent_issued_length_mm=parent.issued_length_mm, parent_consumed_length_mm=parent.consumed_length_mm,
        parent_free_length_mm=_free(parent),
        child_unit_id=str(child.id), child_unit_number=child.unit_number, child_status=child.status,
        child_original_length_mm=child.original_length_mm, child_remaining_length_mm=child.remaining_length_mm,
        child_free_length_mm=_free(child), child_location=child.location,
        child_allocation_eligible=block is None, child_allocation_ineligible_reason=block,
        inward_total_length_mm=inward.received_total_length_mm, inward_units_remaining_plus_consumed_mm=held,
        reconciled=True,
        message=(f"{length_mm} mm split from {parent.unit_number} into {child.unit_number} "
                 f"({out_txn} / {in_txn}); physical length is conserved."
                 + (f" {parent.unit_number} is now fully consumed." if exhausted else "")),
    )


class ContinuousCastingSplitService:
    @staticmethod
    def split(db: Session, req: CCSplitCreate, current_user: Optional[User] = None) -> CCSplitResult:
        """SPLIT: one parent unit -> one new child unit. Free length only; one SPLIT_OUT and one
        SPLIT_IN ledger row; atomic. Stores operation (CC_ISSUE_ROLES). QA is not checked: it
        controls allocation eligibility, which the child inherits through its inward."""
        _require_role(current_user, CC_ISSUE_ROLES, "split continuous-casting stock")
        return _run(db, lambda: _split(db, req, current_user))
