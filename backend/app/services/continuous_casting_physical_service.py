"""Continuous Casting HOLD / HOLD_RELEASE, SCRAP and ADJUSTMENT_IN / ADJUSTMENT_OUT (Phase 9).

Frozen balance model (per unit, all integer mm):

  remaining = INWARD + SPLIT_IN + ADJUSTMENT_IN - SPLIT_OUT - CUT_CONSUME - SCRAP - ADJUSTMENT_OUT
  free      = remaining - reserved - issued

HOLD / HOLD_RELEASE  status only (IN_STOCK <-> ON_HOLD); one zero-length ledger row; no balance moves.
                     A hold is allowed even when reserved or issued length exists. ON_HOLD blocks
                     RESERVE, ISSUE, CUT_CONSUME and SPLIT; RETURN, RELEASE, SCRAP and ADJUSTMENT stay allowed.
SCRAP                remaining - X, scrapped + X, for FREE length only (X <= free). A physical disposal; it
                     is not a consumption. The scrap that takes remaining to 0 sets SCRAPPED (terminal).
ADJUSTMENT_OUT       remaining - X for free length; may never exhaust a unit (a wholly lost bar is a SCRAP).
ADJUSTMENT_IN        remaining + X, only to restore earlier ADJUSTMENT_OUT (cumulative IN <= cumulative OUT),
                     so it can never create length beyond the original receipt.

Reserved, issued and consumed length is never touched by any of these, so no allocation is changed and
none is locked: only the StockUnit is locked (with_for_update + populate_existing), which still serialises
these operations against RESERVE / ISSUE / CUT_CONSUME / RETURN / SPLIT on the same unit. Nothing here
locks a second unit, because a hold does not cascade to a split remnant.

Each operation writes exactly one immutable ledger row and updates the unit in the same transaction, then
re-derives the unit's balances and the inward's conservation from the ledger; any disagreement rolls the
whole operation back:  sum(remaining + consumed + scrapped) = received - sum(ADJUSTMENT_OUT) + sum(ADJUSTMENT_IN).

SCRAP and the two adjustments accept an optional client_request_id (the existing nullable, partially
unique ledger column): replaying the same key and request returns the original result without a second
movement. HOLD and HOLD_RELEASE need no key: a repeat is rejected by the status check. The NC Tracker
remains the disposition authority; nc_record_id on a SCRAP is only a verified pointer.
NOTE: SQLite ignores FOR UPDATE; the lock REQUEST and the post-lock re-read are tested, PostgreSQL
row-lock behaviour itself is not proven by SQLite.
"""
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.roles import CC_HOLD_ROLES, CC_HOLD_RELEASE_ROLES, CC_SCRAP_ROLES, CC_ADJUSTMENT_ROLES
from app.models.audit import AuditLog
from app.models.nc import NCRecord
from app.models.user import User
from app.models.continuous_casting import (
    ContinuousCastingInward, ContinuousCastingStockUnit, ContinuousCastingStockLedger,
    UNIT_STATUS_IN_STOCK, next_cc_ledger_transaction_number,
)
from app.schemas.continuous_casting import (
    CCHoldCreate, CCHoldReleaseCreate, CCScrapCreate, CCAdjustmentCreate, CCUnitMovementResult,
)
from app.services.continuous_casting_service import _require_role, _bad_request
from app.services.continuous_casting_reservation_service import (
    _lock, _ledger_totals, _reconcile, _run, UNIT_STATUS_ON_HOLD, UNIT_STATUS_SCRAPPED, UNIT_STATUS_CONSUMED,
)
from app.services.continuous_casting_split_service import reconcile_inward

HOLD = "HOLD"
HOLD_RELEASE = "HOLD_RELEASE"
SCRAP = "SCRAP"
ADJUSTMENT_IN = "ADJUSTMENT_IN"
ADJUSTMENT_OUT = "ADJUSTMENT_OUT"
Unit, Ledger = ContinuousCastingStockUnit, ContinuousCastingStockLedger
LENGTH_KINDS = (SCRAP, ADJUSTMENT_IN, ADJUSTMENT_OUT)


def _free(unit) -> int:
    return unit.remaining_length_mm - unit.reserved_length_mm - unit.issued_length_mm


def _text(value, label: str, required: bool) -> Optional[str]:
    """Trimmed text, or None when absent. Safe for None (no .strip() on a missing value)."""
    cleaned = value.strip() if isinstance(value, str) and value.strip() else None
    if cleaned is None and required:
        raise _bad_request(f"A {label} is required.")
    return cleaned


def _net_adjustment(totals: dict) -> int:
    return totals.get(ADJUSTMENT_IN, 0) - totals.get(ADJUSTMENT_OUT, 0)


def _build_result(db, kind, unit, inward, txn, length_mm, replayed, message) -> CCUnitMovementResult:
    ledger_remaining_check = _reconcile(db, unit)          # re-derived from the ledger before anything commits
    del ledger_remaining_check
    accounted = reconcile_inward(db, inward)
    totals = _ledger_totals(db, Ledger.stock_unit_id == unit.id)
    return CCUnitMovementResult(
        success=True, movement_type=kind, ledger_transaction_number=txn, replayed=replayed,
        inward_id=str(inward.id), inward_number=inward.inward_number,
        stock_unit_id=str(unit.id), stock_unit_number=unit.unit_number, length_mm=length_mm,
        unit_status=unit.status, unit_remaining_length_mm=unit.remaining_length_mm,
        unit_reserved_length_mm=unit.reserved_length_mm, unit_issued_length_mm=unit.issued_length_mm,
        unit_consumed_length_mm=unit.consumed_length_mm, unit_scrapped_length_mm=unit.scrapped_length_mm,
        unit_free_length_mm=_free(unit), unit_net_adjustment_mm=_net_adjustment(totals),
        inward_received_total_length_mm=inward.received_total_length_mm, inward_accounted_length_mm=accounted,
        reconciled=True, message=message,
    )


def _apply(db: Session, kind: str, req, current_user: User) -> CCUnitMovementResult:
    if req.stock_unit_id is None or req.inward_id is None:
        raise _bad_request("stock_unit_id and inward_id are required.")
    length_mm = getattr(req, "length_mm", 0) if kind in LENGTH_KINDS else 0
    if kind in LENGTH_KINDS and (isinstance(length_mm, bool) or not isinstance(length_mm, int) or length_mm <= 0):
        raise _bad_request("Length must be a positive whole number of millimetres.")
    reason = _text(getattr(req, "reason", None), "reason", True)
    reference = _text(getattr(req, "reference", None), "reference", kind in LENGTH_KINDS)
    key = _text(getattr(req, "client_request_id", None), "client_request_id", False)

    unit = _lock(db, Unit, req.stock_unit_id)                        # the only row lock these operations need
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stock unit not found.")
    if unit.inward_id != req.inward_id:
        raise _bad_request(f"Inward supplied is not the inward of stock unit {unit.unit_number}.")
    inward = db.query(ContinuousCastingInward).filter(
        ContinuousCastingInward.id == unit.inward_id).populate_existing().first()
    if inward is None:
        raise _bad_request("The unit's inward is missing.")

    if key is not None:
        prior = db.query(Ledger).filter(Ledger.client_request_id == key).first()
        if prior is not None:
            if prior.movement_type == kind and prior.stock_unit_id == unit.id and prior.length_mm == length_mm:
                return _build_result(db, kind, unit, inward, prior.transaction_number, prior.length_mm, True,
                                     f"{kind} {prior.length_mm} mm was already recorded as "
                                     f"{prior.transaction_number}; nothing was repeated.")
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "client_request_id was already used for a different request; nothing was saved.")

    nc_record_id = None
    if kind == HOLD:
        if unit.status != UNIT_STATUS_IN_STOCK:
            raise _bad_request(f"Stock unit {unit.unit_number} is {unit.status}; only an {UNIT_STATUS_IN_STOCK} "
                               f"unit can be placed on hold.")
        unit.status = UNIT_STATUS_ON_HOLD
        verb = f"{unit.unit_number} placed ON_HOLD; no balance changed"
    elif kind == HOLD_RELEASE:
        if unit.status != UNIT_STATUS_ON_HOLD:
            raise _bad_request(f"Stock unit {unit.unit_number} is {unit.status}; only an ON_HOLD unit can be "
                               f"released from hold.")
        unit.status = UNIT_STATUS_IN_STOCK
        verb = f"{unit.unit_number} released from hold; no balance changed"
    else:
        if unit.status not in (UNIT_STATUS_IN_STOCK, UNIT_STATUS_ON_HOLD):
            raise _bad_request(f"Stock unit {unit.unit_number} is {unit.status}; a terminal unit cannot be "
                               f"{'scrapped' if kind == SCRAP else 'adjusted'}.")
        free = _free(unit)
        if kind in (SCRAP, ADJUSTMENT_OUT) and length_mm > free:
            what = "scrap" if kind == SCRAP else "adjust out"
            raise _bad_request(
                f"Cannot {what} {length_mm} mm from {unit.unit_number}: only {max(free, 0)} mm is free (reserved "
                f"{unit.reserved_length_mm} mm and issued {unit.issued_length_mm} mm must be released or "
                f"returned first, and consumed {unit.consumed_length_mm} mm cannot be touched).")
        if kind == SCRAP:
            nc_id = getattr(req, "nc_record_id", None)
            if nc_id is not None:
                if db.query(NCRecord.id).filter(NCRecord.id == nc_id).first() is None:
                    raise _bad_request("The NC record referenced does not exist.")
                nc_record_id = nc_id
            unit.remaining_length_mm -= length_mm
            unit.scrapped_length_mm += length_mm
            if unit.remaining_length_mm == 0:
                unit.status = UNIT_STATUS_SCRAPPED                   # terminal: exhausted by scrapping
            verb = f"{length_mm} mm of {unit.unit_number} scrapped"
        elif kind == ADJUSTMENT_OUT:
            if length_mm >= unit.remaining_length_mm:
                raise _bad_request(
                    f"An adjustment cannot remove all of {unit.unit_number} ({unit.remaining_length_mm} mm); a "
                    f"wholly lost bar is recorded as a SCRAP.")
            unit.remaining_length_mm -= length_mm
            verb = f"recorded length of {unit.unit_number} corrected down by {length_mm} mm"
        else:
            totals = _ledger_totals(db, Ledger.stock_unit_id == unit.id)
            restorable = totals.get(ADJUSTMENT_OUT, 0) - totals.get(ADJUSTMENT_IN, 0)
            if length_mm > restorable:
                raise _bad_request(
                    f"Cannot adjust {length_mm} mm in: only {max(restorable, 0)} mm of earlier ADJUSTMENT_OUT on "
                    f"{unit.unit_number} can be restored; an adjustment never creates length beyond the receipt.")
            if (unit.remaining_length_mm + length_mm + unit.consumed_length_mm + unit.scrapped_length_mm
                    > unit.original_length_mm):
                raise _bad_request(f"Adjusting {length_mm} mm in would exceed the original length of {unit.unit_number}.")
            unit.remaining_length_mm += length_mm
            verb = f"recorded length of {unit.unit_number} restored by {length_mm} mm"

    actor = current_user.full_name
    entry = Ledger(
        transaction_number=next_cc_ledger_transaction_number(db), movement_type=kind,
        inward_id=unit.inward_id, stock_unit_id=unit.id, allocation_id=None, related_stock_unit_id=None,
        length_mm=length_mm, piece_qty=None, unit_remaining_after_mm=unit.remaining_length_mm,
        nc_record_id=nc_record_id, reason=reason, reference=reference, client_request_id=key,
        performed_by_id=current_user.id, performed_by_name=actor,
    )
    db.add(entry)
    db.add(AuditLog(
        user_id=current_user.id, user_name=actor, action=f"CC_{kind}", entity="ContinuousCastingStockUnit",
        entity_id=unit.unit_number, new_value=f"{kind} {length_mm} mm on {unit.unit_number}", details=reason,
    ))
    db.flush()
    return _build_result(db, kind, unit, inward, entry.transaction_number, length_mm, False,
                         f"{kind} recorded as {entry.transaction_number}: {verb}.")


class ContinuousCastingPhysicalService:
    @staticmethod
    def hold(db: Session, req: CCHoldCreate, current_user: Optional[User] = None) -> CCUnitMovementResult:
        """HOLD: IN_STOCK -> ON_HOLD. Status only; allowed even with reserved or issued length."""
        _require_role(current_user, CC_HOLD_ROLES, "place continuous-casting stock on hold")
        return _run(db, lambda: _apply(db, HOLD, req, current_user))

    @staticmethod
    def hold_release(db: Session, req: CCHoldReleaseCreate,
                     current_user: Optional[User] = None) -> CCUnitMovementResult:
        """HOLD_RELEASE: ON_HOLD -> IN_STOCK. Status only."""
        _require_role(current_user, CC_HOLD_RELEASE_ROLES, "release continuous-casting stock from hold")
        return _run(db, lambda: _apply(db, HOLD_RELEASE, req, current_user))

    @staticmethod
    def scrap(db: Session, req: CCScrapCreate, current_user: Optional[User] = None) -> CCUnitMovementResult:
        """SCRAP: dispose of FREE length (remaining - X, scrapped + X). Reserved, issued and consumed
        length is never touched."""
        _require_role(current_user, CC_SCRAP_ROLES, "scrap continuous-casting stock")
        return _run(db, lambda: _apply(db, SCRAP, req, current_user))

    @staticmethod
    def adjust_out(db: Session, req: CCAdjustmentCreate, current_user: Optional[User] = None) -> CCUnitMovementResult:
        """ADJUSTMENT_OUT: correct the recorded length down by X (free length only; never exhausts a unit)."""
        _require_role(current_user, CC_ADJUSTMENT_ROLES, "adjust continuous-casting stock")
        return _run(db, lambda: _apply(db, ADJUSTMENT_OUT, req, current_user))

    @staticmethod
    def adjust_in(db: Session, req: CCAdjustmentCreate, current_user: Optional[User] = None) -> CCUnitMovementResult:
        """ADJUSTMENT_IN: restore length removed by an earlier ADJUSTMENT_OUT (never beyond the receipt)."""
        _require_role(current_user, CC_ADJUSTMENT_ROLES, "adjust continuous-casting stock")
        return _run(db, lambda: _apply(db, ADJUSTMENT_IN, req, current_user))
