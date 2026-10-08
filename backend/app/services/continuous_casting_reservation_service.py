"""Continuous Casting RESERVE / RELEASE (Phase 4), ISSUE (Phase 5), CUT_CONSUME (Phase 6) and
RETURN (Phase 7).

RETURN hands ISSUED, not-yet-cut stock back: issued - X on the unit and the allocation, and
nothing else. Remaining is untouched (ISSUE never removed it -- the bar was always whole), and
so are reserved and consumed. The returned length is free again because free = remaining -
reserved - issued. Unlike RESERVE/ISSUE/CUT_CONSUME it is allowed on a SUPERSEDED routing, which
is what un-strands issued stock when a routing is superseded after ISSUE.

RESERVE and RELEASE move only the *reserved* balance. ISSUE moves length from reserved to
issued; the physical bar still exists after it. CUT_CONSUME is the one physical consumption:
it takes length from ISSUED (never from reserved) and the raw length leaves the bar --
issued - X, consumed + X, remaining - X on the unit; issued - X, consumed + X on the allocation.
Each operation writes one immutable ledger row and updates the cached balances in the same
transaction, then reconciles the affected unit and its allocations against the ledger before
committing.

Locking: every operation takes row locks in the SAME order -- StockUnit, then Allocation, then
Routing -- and re-reads each locked row (populate_existing), so balances are computed after
the locks, never from earlier reads. A single global order is what keeps a reserve and a bulk
release from deadlocking each other. NOTE: SQLite ignores FOR UPDATE; the lock REQUEST and the
fresh re-read are tested, but PostgreSQL row-lock behaviour itself is not proven by SQLite.

There is no request-level idempotency key for these operations (none is approved). A collision
on the ledger transaction number is retried (bounded) and then reported as a controlled 409.
"""
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.roles import CC_RESERVE_ROLES, CC_ISSUE_ROLES, CC_CUT_ROLES
from app.models.audit import AuditLog
from app.models.user import User
from app.models.work_order import WorkOrder, WOStatus
from app.models.continuous_casting import (
    ContinuousCastingAllocation, ContinuousCastingRouting, ContinuousCastingStockUnit,
    ContinuousCastingInward, ContinuousCastingStockLedger, MATERIAL_SOURCE_CONTINUOUS_CASTING,
    UNIT_STATUS_IN_STOCK, qa_allocation_block_reason, next_cc_ledger_transaction_number,
)
from app.schemas.continuous_casting import (
    CCReserveCreate, CCReleaseCreate, CCIssueCreate, CCCutConsumeCreate, CCReturnCreate,
    CCRoutingReleaseCreate, CCStockMovementResult,
    CCRoutingReleaseResult,
)
from app.services.continuous_casting_service import _require_role, _bad_request, _is_unique_violation

ROUTING_ACTIVE = "ACTIVE"
ROUTING_SUPERSEDED = "SUPERSEDED"
RESERVE = "RESERVE"
RELEASE = "RELEASE"
ISSUE = "ISSUE"
CUT_CONSUME = "CUT_CONSUME"
RETURN = "RETURN"
UNIT_STATUS_CONSUMED = "CONSUMED"
UNIT_STATUS_SCRAPPED = "SCRAPPED"
UNIT_STATUS_ON_HOLD = "ON_HOLD"
CC_NUMBER_MAX_ATTEMPTS = 3


# ---------------------------------------------------------------- locking / loading
def _lock(db: Session, model, pk):
    """FOR UPDATE + re-read: the returned row reflects the database after the lock is held."""
    return db.query(model).filter(model.id == pk).with_for_update().populate_existing().first()


def _acquire(db: Session, allocation_id):
    """Lock StockUnit -> Allocation -> Routing (always in this order) and return them."""
    ref = db.query(ContinuousCastingAllocation.stock_unit_id, ContinuousCastingAllocation.routing_id).filter(
        ContinuousCastingAllocation.id == allocation_id).first()          # only to learn which unit to lock
    if not ref:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Allocation not found.")
    unit = _lock(db, ContinuousCastingStockUnit, ref.stock_unit_id)
    allocation = _lock(db, ContinuousCastingAllocation, allocation_id)
    routing = _lock(db, ContinuousCastingRouting, allocation.routing_id) if allocation else None
    if not unit or not allocation or not routing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Allocation, stock unit or routing not found.")
    return allocation, unit, routing


# ---------------------------------------------------------------- balances / reconciliation
def _ledger_totals(db: Session, *conditions) -> dict:
    rows = db.query(
        ContinuousCastingStockLedger.movement_type,
        func.coalesce(func.sum(ContinuousCastingStockLedger.length_mm), 0),
    ).filter(*conditions).group_by(ContinuousCastingStockLedger.movement_type).all()
    return {movement: int(total) for movement, total in rows}


def _derive(totals: dict) -> dict:
    """Ledger-derived reserved / issued / consumed. Includes the ISSUE, RETURN and CUT_CONSUME
    terms so later phases reconcile with the same formulas."""
    issue, ret, cut = totals.get("ISSUE", 0), totals.get("RETURN", 0), totals.get("CUT_CONSUME", 0)
    return {
        "reserved": totals.get("RESERVE", 0) - totals.get("RELEASE", 0) - issue,
        "issued": issue - ret - cut,
        "consumed": cut,
    }


def _derive_remaining(totals: dict) -> int:
    """Ledger-derived physical length on a unit: what arrived (INWARD, SPLIT_IN) less what left
    (SPLIT_OUT, CUT_CONSUME). ISSUE, RETURN, RESERVE and RELEASE never change it."""
    return (totals.get("INWARD", 0) + totals.get("SPLIT_IN", 0) + totals.get("ADJUSTMENT_IN", 0)
            - totals.get("SPLIT_OUT", 0) - totals.get("CUT_CONSUME", 0) - totals.get("SCRAP", 0)
            - totals.get("ADJUSTMENT_OUT", 0))


def _reconcile(db: Session, unit: ContinuousCastingStockUnit) -> int:
    """Cached balances must equal the ledger. Returns the ledger-derived reserved length.
    Any disagreement raises, which rolls the whole operation back."""
    unit_totals = _ledger_totals(db, ContinuousCastingStockLedger.stock_unit_id == unit.id)
    unit_derived = _derive(unit_totals)
    cached = {"reserved": unit.reserved_length_mm, "issued": unit.issued_length_mm,
              "consumed": unit.consumed_length_mm}
    if cached != unit_derived:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Stock reconciliation failed for {unit.unit_number} (cached {cached}, ledger {unit_derived}); "
            f"nothing was changed.")
    ledger_remaining = _derive_remaining(unit_totals)
    if unit.remaining_length_mm != ledger_remaining:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Stock reconciliation failed for {unit.unit_number}: remaining {unit.remaining_length_mm} mm but "
            f"the ledger gives {ledger_remaining} mm; nothing was changed.")
    if unit.scrapped_length_mm != unit_totals.get("SCRAP", 0):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Stock reconciliation failed for {unit.unit_number}: scrapped {unit.scrapped_length_mm} mm but "
            f"the ledger gives {unit_totals.get('SCRAP', 0)} mm; nothing was changed.")
    if unit.status == UNIT_STATUS_CONSUMED and (unit.remaining_length_mm != 0 or unit.consumed_length_mm <= 0):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Unit {unit.unit_number} is CONSUMED but is not exhausted by consumption; nothing was changed.")
    if unit.status == UNIT_STATUS_SCRAPPED and (unit.remaining_length_mm != 0 or unit.scrapped_length_mm <= 0):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Unit {unit.unit_number} is SCRAPPED but is not exhausted by scrapping; nothing was changed.")
    if unit.remaining_length_mm == 0 and unit.status not in (UNIT_STATUS_CONSUMED, UNIT_STATUS_SCRAPPED):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Unit {unit.unit_number} has no length left but is {unit.status}; nothing was changed.")
    if unit.status in (UNIT_STATUS_IN_STOCK, UNIT_STATUS_ON_HOLD):
        # A live unit's hold status must follow its latest HOLD / HOLD_RELEASE ledger row.
        last_hold = db.query(ContinuousCastingStockLedger.movement_type).filter(
            ContinuousCastingStockLedger.stock_unit_id == unit.id,
            ContinuousCastingStockLedger.movement_type.in_(("HOLD", "HOLD_RELEASE")),
        ).order_by(ContinuousCastingStockLedger.transaction_number.desc()).first()
        expected = UNIT_STATUS_ON_HOLD if last_hold and last_hold[0] == "HOLD" else UNIT_STATUS_IN_STOCK
        if unit.status != expected:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Unit {unit.unit_number} is {unit.status} but its hold history says {expected}; "
                f"nothing was changed.")
    allocations = db.query(ContinuousCastingAllocation).filter(
        ContinuousCastingAllocation.stock_unit_id == unit.id).all()
    for a in allocations:
        derived = _derive(_ledger_totals(db, ContinuousCastingStockLedger.allocation_id == a.id))
        have = {"reserved": a.reserved_length_mm, "issued": a.issued_length_mm, "consumed": a.consumed_length_mm}
        if have != derived:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Allocation {a.allocation_number} does not reconcile with the ledger; nothing was changed.")
    if (sum(a.reserved_length_mm for a in allocations) != unit.reserved_length_mm
            or sum(a.issued_length_mm for a in allocations) != unit.issued_length_mm
            or sum(a.consumed_length_mm for a in allocations) != unit.consumed_length_mm):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Unit {unit.unit_number} does not equal the sum of its allocations; nothing was changed.")
    if (unit.remaining_length_mm < 0 or unit.reserved_length_mm < 0 or unit.issued_length_mm < 0
            or unit.reserved_length_mm + unit.issued_length_mm > unit.remaining_length_mm):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"Unit {unit.unit_number} balances are out of range; nothing was changed.")
    return unit_derived["reserved"]


def _cut_would_exceed_plan(allocation, length_mm: int) -> bool:
    """The plan invariant (reserved + issued + consumed <= planned) evaluated on the state AFTER
    a cut of `length_mm`. A cut only moves length from issued to consumed, so with a consistent
    ledger this never fires; it is defense in depth, like the ISSUE rule."""
    return (allocation.reserved_length_mm + (allocation.issued_length_mm - length_mm)
            + (allocation.consumed_length_mm + length_mm)) > allocation.planned_length_mm


def _issue_would_exceed_plan(allocation, length_mm: int) -> bool:
    """Issued + consumed + this issue must stay within the allocation's planned quantity.
    Defense in depth: the other rules already keep a consistent ledger inside the plan."""
    return allocation.issued_length_mm + allocation.consumed_length_mm + length_mm > allocation.planned_length_mm


def _allocation_status(allocation: ContinuousCastingAllocation, routing_active: bool) -> str:
    if allocation.consumed_length_mm > 0:
        return "CONSUMED" if allocation.consumed_length_mm >= allocation.planned_length_mm else "PARTIALLY_CONSUMED"
    if allocation.issued_length_mm > 0:
        return "ISSUED"
    if allocation.reserved_length_mm > 0:
        return "RESERVED"
    return "PLANNED" if routing_active else "RELEASED"


# ---------------------------------------------------------------- the single stock movement
def _move(db: Session, kind: str, routing_id, allocation_id, length_mm, reason, current_user: User,
          require_superseded: bool = False, stock_unit_id=None, inward_id=None):
    """One RESERVE, RELEASE, ISSUE, CUT_CONSUME or RETURN. length_mm=None on a RELEASE means
    "everything still reserved"; returns None when there is nothing reserved. Does NOT commit."""
    physical = kind in (ISSUE, CUT_CONSUME, RETURN)   # physical operations name the unit being handled
    if (routing_id is None or allocation_id is None or (physical and stock_unit_id is None)
            or (kind == RETURN and inward_id is None)):
        raise _bad_request("routing_id, allocation_id" + (" and stock_unit_id" if physical else "")
                           + (" and inward_id" if kind == RETURN else "") + " are all required.")
    allocation, unit, routing = _acquire(db, allocation_id)
    if allocation.routing_id != routing_id:
        raise _bad_request(
            f"Allocation {allocation.allocation_number} does not belong to the routing supplied.")
    if physical and allocation.stock_unit_id != stock_unit_id:
        raise _bad_request(
            f"Stock unit supplied is not the unit allocated on {allocation.allocation_number}; "
            f"use the unit the allocation was made against.")
    if kind == RETURN and unit.inward_id != inward_id:
        raise _bad_request(
            f"Inward supplied is not the inward of stock unit {unit.unit_number}; hand back the bar from "
            f"its own receipt.")
    wo = db.query(WorkOrder).filter(WorkOrder.id == routing.work_order_id).first()
    if wo is None:
        raise _bad_request("The routing's Work Order is missing.")
    inward = db.query(ContinuousCastingInward).filter(
        ContinuousCastingInward.id == unit.inward_id).populate_existing().first()

    if kind in (RESERVE, ISSUE, CUT_CONSUME):
        # Lifecycle (one rule for all three): only an ACTIVE routing takes new stock movements toward
        # production. Reserved stock on a superseded routing is explicitly released, never issued
        # or cut. (QA is deliberately not re-checked for ISSUE or CUT_CONSUME: that material already
        # passed the reservation gate.)
        noun, verb = {RESERVE: ("new reservations", "reserved"), ISSUE: ("issuing", "issued"),
                      CUT_CONSUME: ("cutting", "cut")}[kind]
        if routing.material_source != MATERIAL_SOURCE_CONTINUOUS_CASTING:
            raise _bad_request(f"Only a CONTINUOUS_CASTING routing can have stock {verb}.")
        if routing.status != ROUTING_ACTIVE:
            raise _bad_request(
                f"Routing v{routing.version} is {routing.status}; {noun} need an ACTIVE routing.")
        if wo.status in (WOStatus.CLOSED, WOStatus.DISPATCHED):
            raise _bad_request(f"Work Order '{wo.wo_number}' is {wo.status.value}; stock cannot be {verb} for it.")
    if kind in (ISSUE, CUT_CONSUME) and unit.status == UNIT_STATUS_ON_HOLD:
        # A quarantined unit takes no step toward production. RETURN and RELEASE stay allowed: they
        # only unwind existing commitments. (Applied after the row lock and re-read.)
        raise _bad_request(
            f"Stock unit {unit.unit_number} is ON_HOLD; {'issuing' if kind == ISSUE else 'cutting'} is blocked "
            f"until the hold is released. Returning or releasing its stock is still allowed.")
    if kind == RETURN:
        # Unlike RESERVE/ISSUE/CUT_CONSUME, RETURN is allowed on a SUPERSEDED routing: it is what
        # un-strands issued stock. Any other routing state (e.g. DRAFT) is still rejected. A closed
        # WO may also hand its issued stock back. QA and unit status are not consulted.
        if routing.material_source != MATERIAL_SOURCE_CONTINUOUS_CASTING:
            raise _bad_request("Only a CONTINUOUS_CASTING routing can have stock returned.")
        if routing.status not in (ROUTING_ACTIVE, ROUTING_SUPERSEDED):
            raise _bad_request(
                f"Routing v{routing.version} is {routing.status}; returning needs an ACTIVE or SUPERSEDED routing.")
    if kind == RESERVE:
        # QA and unit status gate NEW reservations only. ISSUE deliberately does not re-check QA:
        # a valid reservation is not retroactively invalidated by a later QA status change.
        block = qa_allocation_block_reason(inward.qa_status if inward else None)
        if block:
            raise _bad_request(f"Stock unit {unit.unit_number} cannot be reserved: {block}.")
        if unit.status != UNIT_STATUS_IN_STOCK:
            raise _bad_request(
                f"Stock unit {unit.unit_number} cannot be reserved: unit status is {unit.status}; "
                f"reserving requires {UNIT_STATUS_IN_STOCK}.")
    elif require_superseded and routing.status != ROUTING_SUPERSEDED:
        raise _bad_request(f"Routing v{routing.version} is {routing.status}, not SUPERSEDED.")

    # Everything below uses the freshly locked balances.
    if kind == RELEASE and length_mm is None:
        length_mm = allocation.reserved_length_mm
        if length_mm == 0:
            return None
    if isinstance(length_mm, bool) or not isinstance(length_mm, int) or length_mm <= 0:
        raise _bad_request("Length must be a positive whole number of millimetres.")

    if kind == RESERVE:
        plan_left = (allocation.planned_length_mm - allocation.reserved_length_mm
                     - allocation.issued_length_mm - allocation.consumed_length_mm)
        if length_mm > plan_left:
            raise _bad_request(
                f"Cannot reserve {length_mm} mm: only {max(plan_left, 0)} mm of the planned "
                f"{allocation.planned_length_mm} mm remains on allocation {allocation.allocation_number}.")
        free = unit.remaining_length_mm - unit.reserved_length_mm - unit.issued_length_mm
        if length_mm > free:
            raise _bad_request(
                f"Cannot reserve {length_mm} mm from {unit.unit_number}: only {max(free, 0)} mm of "
                f"physical length is free.")
        unit.reserved_length_mm += length_mm
        allocation.reserved_length_mm += length_mm
    elif kind == ISSUE:
        if length_mm > allocation.reserved_length_mm:
            raise _bad_request(
                f"Cannot issue {length_mm} mm: only {allocation.reserved_length_mm} mm is currently reserved on "
                f"allocation {allocation.allocation_number}. Released, already-issued or consumed material "
                f"cannot be issued (issued {allocation.issued_length_mm} mm, consumed "
                f"{allocation.consumed_length_mm} mm).")
        if length_mm > unit.reserved_length_mm:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Unit {unit.unit_number} reserved balance is lower than its allocation's; nothing was changed.")
        if _issue_would_exceed_plan(allocation, length_mm):
            raise _bad_request(
                f"Cannot issue {length_mm} mm: issued plus consumed would exceed the planned "
                f"{allocation.planned_length_mm} mm on allocation {allocation.allocation_number}.")
        # A transfer, not a consumption: reserved -> issued. Remaining and consumed are untouched.
        unit.reserved_length_mm -= length_mm
        unit.issued_length_mm += length_mm
        allocation.reserved_length_mm -= length_mm
        allocation.issued_length_mm += length_mm
    elif kind == CUT_CONSUME:
        if unit.status in (UNIT_STATUS_CONSUMED, UNIT_STATUS_SCRAPPED) or unit.remaining_length_mm <= 0:
            raise _bad_request(f"Stock unit {unit.unit_number} is already fully consumed.")
        if length_mm > unit.issued_length_mm:
            raise _bad_request(
                f"Cannot cut {length_mm} mm: stock unit {unit.unit_number} has only {unit.issued_length_mm} mm "
                f"issued. Only ISSUED material can be cut; reserved material must be issued first.")
        if length_mm > allocation.issued_length_mm:
            raise _bad_request(
                f"Cannot cut {length_mm} mm: only {allocation.issued_length_mm} mm is issued on allocation "
                f"{allocation.allocation_number} (reserved {allocation.reserved_length_mm} mm must be issued first; "
                f"{allocation.consumed_length_mm} mm already consumed).")
        if _cut_would_exceed_plan(allocation, length_mm):
            raise _bad_request(
                f"Cannot cut {length_mm} mm: reserved + issued + consumed would exceed the planned "
                f"{allocation.planned_length_mm} mm on allocation {allocation.allocation_number}.")
        # Physical consumption: issued -> consumed, and the raw length leaves the bar. Reserved is untouched.
        unit.issued_length_mm -= length_mm
        unit.consumed_length_mm += length_mm
        unit.remaining_length_mm -= length_mm
        allocation.issued_length_mm -= length_mm
        allocation.consumed_length_mm += length_mm
        if unit.remaining_length_mm == 0:
            unit.status = UNIT_STATUS_CONSUMED
    elif kind == RETURN:
        if length_mm > allocation.issued_length_mm:
            raise _bad_request(
                f"Cannot return {length_mm} mm: only {allocation.issued_length_mm} mm is currently issued on "
                f"allocation {allocation.allocation_number}. Reserved material is released, not returned, and "
                f"consumed material ({allocation.consumed_length_mm} mm) is gone and can never be returned.")
        if length_mm > unit.issued_length_mm:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Unit {unit.unit_number} issued balance is lower than its allocation's; nothing was changed.")
        # A hand-back: issued -> free. Remaining (the bar is whole), reserved and consumed are untouched.
        unit.issued_length_mm -= length_mm
        allocation.issued_length_mm -= length_mm
    else:
        if length_mm > allocation.reserved_length_mm:
            raise _bad_request(
                f"Cannot release {length_mm} mm: only {allocation.reserved_length_mm} mm is currently reserved on "
                f"allocation {allocation.allocation_number} (issued {allocation.issued_length_mm} mm and consumed "
                f"{allocation.consumed_length_mm} mm cannot be released).")
        if length_mm > unit.reserved_length_mm:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Unit {unit.unit_number} reserved balance is lower than its allocation's; nothing was changed.")
        unit.reserved_length_mm -= length_mm
        allocation.reserved_length_mm -= length_mm

    allocation.status = _allocation_status(allocation, routing.status == ROUTING_ACTIVE)
    actor = current_user.full_name
    default_reason = {
        RESERVE: f"Reserve for {wo.wo_number} routing v{routing.version}",
        RELEASE: f"Release from {wo.wo_number} routing v{routing.version}",
        ISSUE: f"Issue to {wo.wo_number} routing v{routing.version}",
        CUT_CONSUME: f"Cut consumption for {wo.wo_number} routing v{routing.version}",
        RETURN: f"Return from {wo.wo_number} routing v{routing.version}",
    }[kind]
    entry = ContinuousCastingStockLedger(
        transaction_number=next_cc_ledger_transaction_number(db), movement_type=kind,
        inward_id=unit.inward_id, stock_unit_id=unit.id, allocation_id=allocation.id,
        length_mm=length_mm, unit_remaining_after_mm=unit.remaining_length_mm,
        reason=(reason.strip() if isinstance(reason, str) and reason.strip() else default_reason),
        reference=f"{allocation.allocation_number} | {wo.wo_number} routing v{routing.version}",
        performed_by_id=current_user.id, performed_by_name=actor,
    )
    db.add(entry)
    db.add(AuditLog(
        user_id=current_user.id, user_name=actor, action=f"CC_{kind}",
        entity="ContinuousCastingAllocation", entity_id=allocation.allocation_number,
        new_value=f"{kind} {length_mm} mm on {unit.unit_number} ({wo.wo_number} routing v{routing.version})",
        details=entry.reason,
    ))
    db.flush()
    ledger_reserved = _reconcile(db, unit)

    return CCStockMovementResult(
        success=True, movement_type=kind, ledger_transaction_number=entry.transaction_number,
        allocation_id=str(allocation.id), allocation_number=allocation.allocation_number,
        routing_id=str(routing.id), routing_version=routing.version, wo_number=wo.wo_number,
        stock_unit_number=unit.unit_number, inward_number=inward.inward_number if inward else "",
        length_mm=length_mm, allocation_status=allocation.status,
        allocation_planned_length_mm=allocation.planned_length_mm,
        allocation_reserved_length_mm=allocation.reserved_length_mm,
        allocation_issued_length_mm=allocation.issued_length_mm,
        allocation_consumed_length_mm=allocation.consumed_length_mm,
        unit_remaining_length_mm=unit.remaining_length_mm, unit_reserved_length_mm=unit.reserved_length_mm,
        unit_issued_length_mm=unit.issued_length_mm, unit_consumed_length_mm=unit.consumed_length_mm,
        unit_free_length_mm=unit.remaining_length_mm - unit.reserved_length_mm - unit.issued_length_mm,
        ledger_reserved_length_mm=ledger_reserved, reconciled=True,
        message=(f"{kind} {length_mm} mm recorded as {entry.transaction_number}; "
                 + (f"{length_mm} mm of raw length consumed." if kind == CUT_CONSUME
                    else f"{length_mm} mm is free stock again; physical length is unchanged." if kind == RETURN
                    else "physical length is unchanged.")),
    )


def _run(db: Session, attempt):
    """Run one whole operation and commit. A ledger-number collision is retried (bounded);
    any other failure rolls everything back. There is no client_request_id on this path."""
    for n in range(1, CC_NUMBER_MAX_ATTEMPTS + 1):
        try:
            result = attempt()
            db.commit()
            return result
        except IntegrityError as exc:
            db.rollback()
            if not _is_unique_violation(exc):
                raise _bad_request("The change violates a stock integrity rule and was not saved.")
            message = str(getattr(exc, "orig", exc)).lower()
            # a number collision, or two requests racing on one client_request_id (the retry then
            # finds the first one's row and replays it)
            if (("transaction_number" in message or "unit_number" in message or "client_request_id" in message
                 or "cut_number" in message or "ledger_entry_id" in message) and n < CC_NUMBER_MAX_ATTEMPTS):
                continue
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Could not reserve a unique ledger transaction or unit number; nothing was saved. Please retry.")
        except Exception:
            db.rollback()
            raise


class ContinuousCastingReservationService:
    @staticmethod
    def reserve(db: Session, req: CCReserveCreate, current_user: Optional[User] = None) -> CCStockMovementResult:
        """RESERVE: reserved + length_mm on the unit and the allocation, plus one RESERVE
        ledger row. Does not touch remaining, issued or consumed length."""
        _require_role(current_user, CC_RESERVE_ROLES, "reserve continuous-casting stock")
        return _run(db, lambda: _move(db, RESERVE, req.routing_id, req.allocation_id, req.length_mm,
                                      req.reason, current_user))

    @staticmethod
    def release(db: Session, req: CCReleaseCreate, current_user: Optional[User] = None) -> CCStockMovementResult:
        """RELEASE: reserved - length_mm (partial release is fine), plus one RELEASE ledger
        row. Only currently-reserved length can be released, on an ACTIVE or SUPERSEDED routing."""
        _require_role(current_user, CC_RESERVE_ROLES, "release continuous-casting stock")
        return _run(db, lambda: _move(db, RELEASE, req.routing_id, req.allocation_id, req.length_mm,
                                      req.reason, current_user))

    @staticmethod
    def issue(db: Session, req: CCIssueCreate, current_user: Optional[User] = None) -> CCStockMovementResult:
        """ISSUE: move `length_mm` from reserved to issued on the unit and the allocation, plus one
        ISSUE ledger row. Remaining and consumed length are untouched -- the bar is still there.
        Requires an ACTIVE routing and enough currently-reserved length; QA is not re-checked."""
        _require_role(current_user, CC_ISSUE_ROLES, "issue continuous-casting stock")
        return _run(db, lambda: _move(db, ISSUE, req.routing_id, req.allocation_id, req.length_mm,
                                      req.reason, current_user, stock_unit_id=req.stock_unit_id))

    @staticmethod
    def cut_consume(db: Session, req: CCCutConsumeCreate, current_user: Optional[User] = None) -> CCStockMovementResult:
        """CUT_CONSUME: the actual cut. Takes `length_mm` from ISSUED stock only: unit and allocation
        issued - X and consumed + X, unit remaining - X; reserved is untouched. Writes exactly one
        CUT_CONSUME ledger row (no piece-count change, no hidden second transaction). Needs an
        ACTIVE routing; QA is not re-checked."""
        _require_role(current_user, CC_CUT_ROLES, "record continuous-casting cut consumption")
        return _run(db, lambda: _move(db, CUT_CONSUME, req.routing_id, req.allocation_id, req.length_mm,
                                      req.reason, current_user, stock_unit_id=req.stock_unit_id))

    @staticmethod
    def return_stock(db: Session, req: CCReturnCreate, current_user: Optional[User] = None) -> CCStockMovementResult:
        """RETURN: hand ISSUED, not-yet-cut stock back. issued - X on the unit and the allocation;
        remaining, reserved and consumed are untouched, so the length is simply free again. One
        RETURN ledger row; earlier ISSUE / CUT_CONSUME rows are never touched. Allowed on an ACTIVE
        or SUPERSEDED routing; QA is not re-checked. Store (CC_ISSUE_ROLES): the physical counterpart of ISSUE."""
        _require_role(current_user, CC_ISSUE_ROLES, "return continuous-casting stock")
        return _run(db, lambda: _move(db, RETURN, req.routing_id, req.allocation_id, req.length_mm,
                                      req.reason, current_user, stock_unit_id=req.stock_unit_id,
                                      inward_id=req.inward_id))

    @staticmethod
    def release_superseded_routing(db: Session, req: CCRoutingReleaseCreate,
                                   current_user: Optional[User] = None) -> CCRoutingReleaseResult:
        """Explicitly release everything still reserved under a SUPERSEDED routing, one RELEASE
        ledger row per allocation, in a single transaction. Allocations that never reserved
        anything need no release (they never changed stock) and produce no ledger row."""
        _require_role(current_user, CC_RESERVE_ROLES, "release continuous-casting stock")

        def attempt():
            routing = db.query(ContinuousCastingRouting).filter(
                ContinuousCastingRouting.id == req.routing_id).first()
            if not routing:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Routing not found.")
            if routing.status != ROUTING_SUPERSEDED:
                raise _bad_request(
                    f"Routing v{routing.version} is {routing.status}; only a SUPERSEDED routing is released this way.")
            wo = db.query(WorkOrder).filter(WorkOrder.id == routing.work_order_id).first()
            # Fixed (unit, allocation) order across every operation: no lock-order cycles.
            candidates = db.query(ContinuousCastingAllocation.id).filter(
                ContinuousCastingAllocation.routing_id == routing.id,
                ContinuousCastingAllocation.reserved_length_mm > 0,
            ).order_by(ContinuousCastingAllocation.stock_unit_id, ContinuousCastingAllocation.id).all()
            reason = (req.reason.strip() if isinstance(req.reason, str) and req.reason.strip()
                      else f"Routing v{routing.version} superseded")
            releases = []
            for (allocation_id,) in candidates:
                done = _move(db, RELEASE, routing.id, allocation_id, None, reason, current_user,
                             require_superseded=True)
                if done is not None:
                    releases.append(done)
            total = sum(r.length_mm for r in releases)
            return CCRoutingReleaseResult(
                success=True, routing_id=str(routing.id), routing_version=routing.version,
                wo_number=wo.wo_number if wo else "", allocations_released=len(releases),
                total_released_length_mm=total, releases=releases,
                message=(f"Released {total} mm across {len(releases)} allocation(s) of superseded routing "
                         f"v{routing.version}." if releases else
                         f"Superseded routing v{routing.version} has no reserved stock to release."),
            )

        return _run(db, attempt)
