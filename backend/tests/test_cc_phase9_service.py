"""Continuous Casting HOLD / HOLD_RELEASE / SCRAP / ADJUSTMENT_IN / ADJUSTMENT_OUT (Phase 9).
In-memory SQLite only; no database file.

Frozen model, per unit (integer mm):
  remaining = INWARD + SPLIT_IN + ADJUSTMENT_IN - SPLIT_OUT - CUT_CONSUME - SCRAP - ADJUSTMENT_OUT
  free      = remaining - reserved - issued
  inward    : sum(remaining + consumed + scrapped) = received - sum(ADJUSTMENT_OUT) + sum(ADJUSTMENT_IN)
HOLD changes status only. SCRAP/ADJUSTMENT_OUT act on FREE length only. ADJUSTMENT_IN only restores
earlier ADJUSTMENT_OUT. SQLite ignores FOR UPDATE, so PostgreSQL row-lock behaviour is not proven; the
lock request/order, the post-lock re-read, rollback and the invariants are.
"""
import random
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query

from app.core.database import Base
from app.models import *  # noqa: F401,F403
from app.models.audit import AuditLog
from app.models.nc import NCRecord
from app.models.user import User, UserRole
from app.schemas.continuous_casting import (
    CCHoldCreate, CCHoldReleaseCreate, CCScrapCreate, CCAdjustmentCreate,
)
import app.services.continuous_casting_physical_service as ph_svc
import app.services.continuous_casting_reservation_service as rv_svc
from app.services.continuous_casting_physical_service import ContinuousCastingPhysicalService as Phys

from test_cc_reservation_service import (  # noqa: F401
    db, shared, world, Ledger, Alloc, Unit, Routing, Inward,
    _user, make_wo, _material, accepted_units, new_routing, supersede, allocate, reserve, release,
    count, rows, oms_state, snapshot, fresh, ledger_totals, assert_reconciled, _raising_listener, cc,
)
from test_cc_issue_service import issue  # noqa: F401
from test_cc_cut_consume_service import w1000, cut  # noqa: F401
from test_cc_return_service import ret  # noqa: F401
from test_cc_split_service import bar, split, child_of  # noqa: F401

ALL_ROLES = list(UserRole)


# ------------------------------------------------------------------ helpers
def _ids(unit, **kw):
    return dict(stock_unit_id=unit.id, inward_id=unit.inward_id, **kw)


def hold(db, unit, reason="suspect surface crack", user=None, **kw):
    return Phys.hold(db, CCHoldCreate(**_ids(unit), reason=reason, **kw), user or _user(db, UserRole.QA))


def unhold(db, unit, reason="re-inspected, acceptable", user=None, **kw):
    return Phys.hold_release(db, CCHoldReleaseCreate(**_ids(unit), reason=reason, **kw), user or _user(db, UserRole.QA))


def scrap(db, unit, x, user=None, reason="unusable, to melting", reference="SCRAP-001", **kw):
    return Phys.scrap(db, CCScrapCreate(**_ids(unit), length_mm=x, reason=reason, reference=reference, **kw),
                      user or _user(db, UserRole.STORE))


def adj_out(db, unit, x, user=None, reason="stock-take measured shorter", reference="COUNT-001", **kw):
    return Phys.adjust_out(db, CCAdjustmentCreate(**_ids(unit), length_mm=x, reason=reason, reference=reference, **kw),
                           user or _user(db, UserRole.ADMIN))


def adj_in(db, unit, x, user=None, reason="re-measured, earlier correction was wrong", reference="COUNT-002", **kw):
    return Phys.adjust_in(db, CCAdjustmentCreate(**_ids(unit), length_mm=x, reason=reason, reference=reference, **kw),
                          user or _user(db, UserRole.ADMIN))


def state(db, unit_id):
    u = fresh(db, Unit, unit_id)
    return (u.remaining_length_mm, u.reserved_length_mm, u.issued_length_mm, u.consumed_length_mm,
            u.scrapped_length_mm, u.status)


def formula(totals):
    g = totals.get
    return (g("INWARD", 0) + g("SPLIT_IN", 0) + g("ADJUSTMENT_IN", 0)
            - g("SPLIT_OUT", 0) - g("CUT_CONSUME", 0) - g("SCRAP", 0) - g("ADJUSTMENT_OUT", 0))


def assert_unit_ok(db, unit_id):
    """Independent re-derivation of every balance and the terminal-status rules (not the service's own)."""
    u = fresh(db, Unit, unit_id)
    t = ledger_totals(db, u.id)
    assert u.remaining_length_mm == formula(t)
    assert u.scrapped_length_mm == t.get("SCRAP", 0) and u.consumed_length_mm == t.get("CUT_CONSUME", 0)
    assert_reconciled(db, u)
    assert u.remaining_length_mm + u.consumed_length_mm + u.scrapped_length_mm <= u.original_length_mm
    if u.status == "CONSUMED":
        assert u.remaining_length_mm == 0 and u.consumed_length_mm > 0
    if u.status == "SCRAPPED":
        assert u.remaining_length_mm == 0 and u.scrapped_length_mm > 0
    assert (u.remaining_length_mm == 0) == (u.status in ("CONSUMED", "SCRAPPED"))
    holds = [m for (m,) in db.query(Ledger.movement_type).filter(
        Ledger.stock_unit_id == u.id, Ledger.movement_type.in_(("HOLD", "HOLD_RELEASE"))
    ).order_by(Ledger.transaction_number).all()]
    if u.status in ("IN_STOCK", "ON_HOLD"):
        assert (u.status == "ON_HOLD") == bool(holds and holds[-1] == "HOLD")


def assert_conserved(db, inward_id):
    """sum(remaining + consumed + scrapped) = received - sum(ADJUSTMENT_OUT) + sum(ADJUSTMENT_IN)."""
    db.expire_all()
    units = db.query(Unit).filter(Unit.inward_id == inward_id).all()
    held = sum(u.remaining_length_mm + u.consumed_length_mm + u.scrapped_length_mm for u in units)
    t = {m: int(s) for m, s in db.query(Ledger.movement_type, func.sum(Ledger.length_mm)).filter(
        Ledger.inward_id == inward_id).group_by(Ledger.movement_type).all()}
    received = db.get(Inward, inward_id).received_total_length_mm
    assert t.get("INWARD", 0) == received == sum(u.original_length_mm for u in units if u.parent_unit_id is None)
    assert t.get("SPLIT_OUT", 0) == t.get("SPLIT_IN", 0)
    assert held == received - t.get("ADJUSTMENT_OUT", 0) + t.get("ADJUSTMENT_IN", 0)
    return held


def last_row(db):
    return db.query(Ledger).order_by(Ledger.transaction_number.desc()).first()


@pytest.fixture()
def held_bar(bar):
    hold(bar["db"], bar["unit"])
    return bar


# ================================================================== HOLD
def test_hold_changes_status_only_and_writes_one_zero_length_row(bar):
    db, unit = bar["db"], bar["unit"]
    uid, iid = unit.id, unit.inward_id
    before_rows = rows(db, "cc_stock_ledger")
    qa = _user(db, UserRole.QA)
    r = hold(db, unit, user=qa)
    assert r.success and r.reconciled and r.movement_type == "HOLD" and r.unit_status == "ON_HOLD" and r.length_mm == 0
    assert state(db, uid) == (1000, 0, 0, 0, 0, "ON_HOLD")
    assert (r.unit_remaining_length_mm, r.unit_free_length_mm, r.unit_net_adjustment_mm) == (1000, 1000, 0)
    assert count(db, "cc_stock_ledger") == len(before_rows) + 1
    row = last_row(db)
    assert row.movement_type == "HOLD" and row.transaction_number == r.ledger_transaction_number
    assert row.length_mm == 0 and row.allocation_id is None and row.related_stock_unit_id is None
    assert row.piece_qty is None and row.unit_remaining_after_mm == 1000 and row.reference is None
    assert row.reason == "suspect surface crack" and row.client_request_id is None and row.nc_record_id is None
    assert row.stock_unit_id == uid and row.inward_id == iid
    assert row.performed_by_id == qa.id and row.performed_by_name == qa.full_name
    assert [x for x in rows(db, "cc_stock_ledger") if x in before_rows] == before_rows
    assert db.query(AuditLog).filter(AuditLog.action == "CC_HOLD").one().entity_id == unit.unit_number
    assert "unit status is ON_HOLD" in cc.allocation_ineligibility_reason(fresh(db, Unit, uid))
    assert_unit_ok(db, uid), assert_conserved(db, iid)
    row.reason = "tamper"
    with pytest.raises(ValueError):
        db.flush()
    db.rollback()


def test_hold_reference_is_optional_and_stored_when_given(bar):
    db, unit = bar["db"], bar["unit"]
    hold(db, unit, reference="NCR-77")
    assert last_row(db).reference == "NCR-77"


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_hold_and_release_reason_is_mandatory(bar, bad):
    db, unit = bar["db"], bar["unit"]
    if bad is None:
        with pytest.raises(ValidationError):
            CCHoldCreate(stock_unit_id=unit.id, inward_id=unit.inward_id)
        with pytest.raises(ValidationError):
            CCHoldReleaseCreate(stock_unit_id=unit.id, inward_id=unit.inward_id)
    else:
        with pytest.raises(ValidationError):
            CCHoldCreate(**_ids(unit), reason=bad)
        with pytest.raises(ValidationError):
            CCHoldReleaseCreate(**_ids(unit), reason=bad)
    raw = CCHoldCreate.model_construct(**_ids(unit), reason=bad, reference=None)        # bypass the schema
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Phys.hold(db, raw, _user(db, UserRole.QA))
    assert e.value.status_code == 400 and "reason" in e.value.detail and snapshot(db) == before


def test_repeated_hold_is_rejected_and_changes_nothing(held_bar):
    db, unit = held_bar["db"], held_bar["unit"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        hold(db, unit)
    assert e.value.status_code == 400 and "ON_HOLD" in e.value.detail and snapshot(db) == before


def test_a_consumed_unit_cannot_be_held(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 1000), issue(db, rid, alloc, 1000), cut(db, rid, alloc, 1000)
    assert fresh(db, Unit, unit.id).status == "CONSUMED"
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        hold(db, unit)
    assert e.value.status_code == 400 and "CONSUMED" in e.value.detail and snapshot(db) == before


def test_a_scrapped_unit_cannot_be_held_or_released(bar):
    db, unit = bar["db"], bar["unit"]
    scrap(db, unit, 1000)
    for fn in (hold, unhold):
        before = snapshot(db)
        with pytest.raises(HTTPException) as e:
            fn(db, unit)
        assert e.value.status_code == 400 and "SCRAPPED" in e.value.detail and snapshot(db) == before


def test_hold_is_allowed_on_a_reserved_unit_without_changing_it(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600)
    allocs = rows(db, "cc_allocations")
    r = hold(db, unit)
    assert state(db, unit.id) == (1000, 600, 0, 0, 0, "ON_HOLD") and r.unit_free_length_mm == 400
    assert rows(db, "cc_allocations") == allocs                    # no allocation is touched or re-statused
    assert_unit_ok(db, unit.id)


def test_hold_is_allowed_on_an_issued_unit_without_changing_it(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 400)
    allocs = rows(db, "cc_allocations")
    hold(db, unit)
    assert state(db, unit.id) == (1000, 200, 400, 0, 0, "ON_HOLD") and rows(db, "cc_allocations") == allocs
    assert_unit_ok(db, unit.id)


def test_hold_is_allowed_on_a_partially_consumed_unit(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 600), cut(db, rid, alloc, 200)
    hold(db, unit)
    assert state(db, unit.id) == (800, 0, 400, 200, 0, "ON_HOLD")
    assert_unit_ok(db, unit.id)


def test_hold_on_a_remnant_child_is_independent_and_does_not_cascade(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    uid, iid = unit.id, unit.inward_id
    reserve(db, rid, alloc, 700), issue(db, rid, alloc, 700), cut(db, rid, alloc, 700)
    c = child_of(db, split(db, unit, 300))
    hold(db, c)
    assert state(db, c.id) == (300, 0, 0, 0, 0, "ON_HOLD")
    assert state(db, uid) == (0, 0, 0, 700, 0, "CONSUMED")           # the parent is untouched
    unhold(db, c)
    assert state(db, c.id)[-1] == "IN_STOCK"
    assert_conserved(db, iid)


def test_a_hold_never_cascades_to_a_split_child_or_from_the_inward_qa_hold(bar):
    db, unit = bar["db"], bar["unit"]
    uid, iid = unit.id, unit.inward_id
    c = child_of(db, split(db, unit, 300))
    hold(db, fresh(db, Unit, uid))
    assert state(db, c.id)[-1] == "IN_STOCK" and state(db, uid)[-1] == "ON_HOLD"
    unhold(db, fresh(db, Unit, uid))
    db.get(Inward, iid).qa_status = "ON_HOLD"                          # an inward QA hold is a separate concept
    db.commit()
    assert state(db, uid)[-1] == "IN_STOCK" and state(db, c.id)[-1] == "IN_STOCK"
    assert "ON_HOLD" in cc.allocation_ineligibility_reason(fresh(db, Unit, uid))   # but QA still blocks allocation


def test_hold_leaves_the_oms_untouched(w1000):
    db, unit = w1000["db"], w1000["unit"]
    before = oms_state(db)
    hold(db, unit), unhold(db, unit), scrap(db, unit, 100)
    assert oms_state(db) == before
    assert count(db, "nc_records") == 0


# ------------------------------------------------------------------ HOLD_RELEASE
def test_hold_release_returns_to_in_stock_without_changing_balances(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    uid, iid = unit.id, unit.inward_id
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 300)
    hold(db, unit)
    before_rows = rows(db, "cc_stock_ledger")
    qa = _user(db, UserRole.QA)
    r = unhold(db, unit, user=qa, reference="QA-OK-9")
    assert r.movement_type == "HOLD_RELEASE" and r.unit_status == "IN_STOCK" and r.length_mm == 0
    assert state(db, uid) == (1000, 300, 300, 0, 0, "IN_STOCK")
    assert count(db, "cc_stock_ledger") == len(before_rows) + 1
    row = last_row(db)
    assert (row.movement_type, row.length_mm, row.reference, row.reason) == (
        "HOLD_RELEASE", 0, "QA-OK-9", "re-inspected, acceptable")
    assert row.allocation_id is None and row.related_stock_unit_id is None and row.piece_qty is None
    assert row.unit_remaining_after_mm == 1000 and row.performed_by_id == qa.id
    assert db.query(AuditLog).filter(AuditLog.action == "CC_HOLD_RELEASE").count() == 1
    assert_unit_ok(db, uid), assert_conserved(db, iid)


def test_hold_release_requires_a_held_unit_and_cannot_repeat(bar):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        unhold(db, unit)                                          # IN_STOCK, not held
    assert e.value.status_code == 400 and "only an ON_HOLD unit" in e.value.detail and snapshot(db) == before
    hold(db, unit), unhold(db, unit)
    with pytest.raises(HTTPException):
        unhold(db, unit)


def test_a_released_unit_can_be_held_again(bar):
    db, unit = bar["db"], bar["unit"]
    hold(db, unit), unhold(db, unit), hold(db, unit)
    assert state(db, unit.id)[-1] == "ON_HOLD"
    assert_unit_ok(db, unit.id)


# ------------------------------------------------------------------ roles
@pytest.mark.parametrize("role,hold_ok,release_ok,scrap_ok,adjust_ok", [
    (UserRole.ADMIN, True, True, True, True),
    (UserRole.STORE, True, False, True, False),
    (UserRole.QA, True, True, False, False),
    (UserRole.PLANNER, False, False, False, False),
    (UserRole.PRODUCTION_MANAGER, False, False, False, False),
    (UserRole.ENGINEERING, False, False, False, False),
    (UserRole.DISPATCH, False, False, False, False),
    (UserRole.CEO, False, False, False, False),
    (UserRole.MACHINE_OPERATOR, False, False, False, False),
])
def test_role_matrix(bar, role, hold_ok, release_ok, scrap_ok, adjust_ok):
    db, unit = bar["db"], bar["unit"]
    who = _user(db, role)
    admin = _user(db, UserRole.ADMIN)

    def attempt(fn, ok):
        before = snapshot(db)
        if ok:
            assert fn().success
        else:
            with pytest.raises(HTTPException) as e:
                fn()
            assert e.value.status_code == 403 and snapshot(db) == before

    attempt(lambda: hold(db, unit, user=who), hold_ok)
    if not hold_ok:
        hold(db, unit, user=admin)                                # so the release attempt is reachable
    elif state(db, unit.id)[-1] != "ON_HOLD":
        hold(db, unit, user=admin)
    attempt(lambda: unhold(db, unit, user=who), release_ok)
    attempt(lambda: scrap(db, unit, 10, user=who), scrap_ok)
    attempt(lambda: adj_out(db, unit, 10, user=who), adjust_ok)


def test_anonymous_cannot_do_any_phase9_operation(bar):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)
    calls = (lambda: Phys.hold(db, CCHoldCreate(**_ids(unit), reason="x"), None),
             lambda: Phys.hold_release(db, CCHoldReleaseCreate(**_ids(unit), reason="x"), None),
             lambda: Phys.scrap(db, CCScrapCreate(**_ids(unit), length_mm=1, reason="x", reference="y"), None),
             lambda: Phys.adjust_out(db, CCAdjustmentCreate(**_ids(unit), length_mm=1, reason="x", reference="y"), None),
             lambda: Phys.adjust_in(db, CCAdjustmentCreate(**_ids(unit), length_mm=1, reason="x", reference="y"), None))
    for call in calls:
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 403
    assert snapshot(db) == before


def test_no_new_user_role_was_introduced():
    assert {r.name for r in UserRole} >= {"ADMIN", "STORE", "QA", "PLANNER", "PRODUCTION_MANAGER", "ENGINEERING"}
    from app.core import roles
    assert roles.CC_HOLD_ROLES == (UserRole.ADMIN, UserRole.STORE, UserRole.QA)
    assert roles.CC_HOLD_RELEASE_ROLES == (UserRole.ADMIN, UserRole.QA)
    assert roles.CC_SCRAP_ROLES == (UserRole.ADMIN, UserRole.STORE)
    assert roles.CC_ADJUSTMENT_ROLES == (UserRole.ADMIN,)


# ================================================================== ON_HOLD blocking matrix
def test_hold_blocks_reserve(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    hold(db, unit)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        reserve(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "ON_HOLD" in e.value.detail and snapshot(db) == before


def test_reserve_hold_issue_is_rejected_but_reserve_issue_works_when_in_stock(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600)
    assert issue(db, rid, alloc, 100).success                       # IN_STOCK: unchanged behaviour
    hold(db, unit)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "ON_HOLD" in e.value.detail and "issuing is blocked" in e.value.detail
    assert snapshot(db) == before
    unhold(db, unit)
    assert issue(db, rid, alloc, 100).unit_issued_length_mm == 200   # the block ends with the hold


def test_issue_hold_cut_is_rejected_but_cut_works_when_in_stock(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 600)
    assert cut(db, rid, alloc, 100).success
    hold(db, unit)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        cut(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "ON_HOLD" in e.value.detail and "cutting is blocked" in e.value.detail
    assert snapshot(db) == before
    unhold(db, unit)
    assert cut(db, rid, alloc, 100).unit_consumed_length_mm == 200


def test_issue_hold_return_is_allowed(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 600)
    hold(db, unit)
    r = ret(db, rid, alloc, 250)
    assert (r.unit_issued_length_mm, r.unit_remaining_length_mm) == (350, 1000)
    assert fresh(db, Unit, unit.id).status == "ON_HOLD"
    assert_unit_ok(db, unit.id)


def test_reserve_hold_release_is_allowed(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600)
    hold(db, unit)
    r = release(db, rid, alloc, 600)
    assert r.unit_reserved_length_mm == 0 and fresh(db, Unit, unit.id).status == "ON_HOLD"
    assert_unit_ok(db, unit.id)


def test_reserve_issue_hold_return_release_lifecycle(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    iid = unit.inward_id
    reserve(db, rid, alloc, 1000), issue(db, rid, alloc, 600)           # reserved 400, issued 600
    hold(db, unit)
    ret(db, rid, alloc, 600)                                             # issued 0
    release(db, rid, alloc, 400)                                         # reserved 0, all free again
    assert state(db, unit.id) == (1000, 0, 0, 0, 0, "ON_HOLD")
    unhold(db, unit)
    assert reserve(db, rid, alloc, 1000).unit_reserved_length_mm == 1000   # fully usable again
    assert_unit_ok(db, unit.id), assert_conserved(db, iid)


def test_hold_blocks_split(bar):
    db, unit = bar["db"], bar["unit"]
    hold(db, unit)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        split(db, unit, 100)
    assert e.value.status_code == 400 and "ON_HOLD" in e.value.detail and snapshot(db) == before
    assert db.query(Unit).count() == 1                                   # no child: a hold cannot be bypassed


def test_hold_allows_scrap_and_adjustment(held_bar):
    db, unit = held_bar["db"], held_bar["unit"]
    assert scrap(db, unit, 100).unit_status == "ON_HOLD"
    assert adj_out(db, unit, 40).unit_status == "ON_HOLD"
    assert adj_in(db, unit, 40).unit_status == "ON_HOLD"
    assert state(db, unit.id) == (900, 0, 0, 0, 100, "ON_HOLD")
    assert_unit_ok(db, unit.id)


def test_cut_after_split_hold_scrap_lifecycle(w1000):
    """CUT -> SPLIT -> HOLD -> SCRAP: the remnant child is quarantined and then scrapped."""
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    uid, iid = unit.id, unit.inward_id
    reserve(db, rid, alloc, 700), issue(db, rid, alloc, 700), cut(db, rid, alloc, 700)
    c = child_of(db, split(db, unit, 300))
    hold(db, c)
    r = scrap(db, c, 300)
    assert r.unit_status == "SCRAPPED" and r.unit_remaining_length_mm == 0 and r.unit_scrapped_length_mm == 300
    assert state(db, uid) == (0, 0, 0, 700, 0, "CONSUMED") and state(db, c.id) == (0, 0, 0, 0, 300, "SCRAPPED")
    assert assert_conserved(db, iid) == 1000                              # 0+700+0 + 0+0+300
    assert_unit_ok(db, uid), assert_unit_ok(db, c.id)


def test_superseded_routing_return_hold_and_scrap(w1000):
    db, unit, alloc, rid, mat = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"], w1000["mat"]
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 600)
    supersede(db, mat)
    hold(db, unit)
    assert ret(db, rid, alloc, 600).unit_issued_length_mm == 0           # RETURN still works on SUPERSEDED + ON_HOLD
    assert scrap(db, unit, 100).unit_remaining_length_mm == 900
    unhold(db, unit)
    assert state(db, unit.id) == (900, 0, 0, 0, 100, "IN_STOCK")
    with pytest.raises(HTTPException):
        cut(db, rid, alloc, 1)                                            # CUT_CONSUME is still ACTIVE-only
    assert_unit_ok(db, unit.id)


# ================================================================== SCRAP
def test_partial_scrap_of_free_stock(bar):
    db, unit = bar["db"], bar["unit"]
    uid, iid = unit.id, unit.inward_id
    before_rows = rows(db, "cc_stock_ledger")
    store = _user(db, UserRole.STORE)
    r = scrap(db, unit, 100, user=store)
    assert (r.movement_type, r.length_mm, r.unit_status) == ("SCRAP", 100, "IN_STOCK")
    assert state(db, uid) == (900, 0, 0, 0, 100, "IN_STOCK")
    assert (r.unit_remaining_length_mm, r.unit_scrapped_length_mm, r.unit_free_length_mm) == (900, 100, 900)
    assert r.inward_accounted_length_mm == 1000 == r.inward_received_total_length_mm
    assert count(db, "cc_stock_ledger") == len(before_rows) + 1
    row = last_row(db)
    assert row.movement_type == "SCRAP" and row.length_mm == 100 and row.unit_remaining_after_mm == 900
    assert row.allocation_id is None and row.related_stock_unit_id is None and row.piece_qty is None
    assert (row.reason, row.reference) == ("unusable, to melting", "SCRAP-001") and row.nc_record_id is None
    assert row.performed_by_id == store.id and row.stock_unit_id == uid and row.inward_id == iid
    assert db.query(AuditLog).filter(AuditLog.action == "CC_SCRAP").count() == 1
    assert db.query(Inward).one().received_piece_count == 1               # the receipt fact is untouched
    assert count(db, "cc_stock_units") == 1                               # no unit created or removed
    assert assert_conserved(db, iid) == 1000
    assert_unit_ok(db, uid)
    scrap(db, unit, 250)
    assert state(db, uid) == (650, 0, 0, 0, 350, "IN_STOCK") and assert_conserved(db, iid) == 1000


def test_full_scrap_makes_the_unit_scrapped_and_terminal(bar):
    db, unit = bar["db"], bar["unit"]
    uid, iid = unit.id, unit.inward_id
    r = scrap(db, unit, 1000)
    assert (r.unit_status, r.unit_remaining_length_mm, r.unit_scrapped_length_mm) == ("SCRAPPED", 0, 1000)
    assert state(db, uid) == (0, 0, 0, 0, 1000, "SCRAPPED")
    assert assert_conserved(db, iid) == 1000
    before = snapshot(db)
    for fn in (lambda: scrap(db, unit, 1), lambda: adj_out(db, unit, 1), lambda: adj_in(db, unit, 1),
               lambda: hold(db, unit), lambda: unhold(db, unit), lambda: split(db, unit, 1)):
        with pytest.raises(HTTPException) as e:
            fn()
        assert e.value.status_code == 400
    assert snapshot(db) == before                                          # a terminal unit is never reopened
    assert_unit_ok(db, uid)


def test_scrap_on_an_on_hold_unit_keeps_it_on_hold_until_exhausted(held_bar):
    db, unit = held_bar["db"], held_bar["unit"]
    assert scrap(db, unit, 400).unit_status == "ON_HOLD"
    assert scrap(db, unit, 600).unit_status == "SCRAPPED"                  # terminal status overrides the hold
    assert_unit_ok(db, unit.id)


def test_scrap_cannot_touch_reserved_or_issued_length(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 300)               # reserved 300, issued 300, free 400
    before = snapshot(db)
    for x in (401, 700, 1000):
        with pytest.raises(HTTPException) as e:
            scrap(db, unit, x)
        assert e.value.status_code == 400 and "only 400 mm is free" in e.value.detail
        assert "released or returned first" in e.value.detail
    assert snapshot(db) == before
    allocs = rows(db, "cc_allocations")
    r = scrap(db, unit, 400)
    assert state(db, unit.id) == (600, 300, 300, 0, 400, "IN_STOCK")       # reserved/issued/consumed unchanged
    assert rows(db, "cc_allocations") == allocs
    assert r.unit_free_length_mm == 0


def test_issued_material_must_be_returned_before_it_can_be_scrapped(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 1000), issue(db, rid, alloc, 1000)
    with pytest.raises(HTTPException) as e:
        scrap(db, unit, 1)
    assert e.value.status_code == 400 and "issued 1000 mm" in e.value.detail
    ret(db, rid, alloc, 1000)
    assert scrap(db, unit, 1000).unit_status == "SCRAPPED"                # return first, then it is free


def test_consumed_material_cannot_be_scrapped_only_what_remains(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 700), issue(db, rid, alloc, 700), cut(db, rid, alloc, 700)    # remaining 300, consumed 700
    with pytest.raises(HTTPException) as e:
        scrap(db, unit, 301)
    assert e.value.status_code == 400 and "only 300 mm is free" in e.value.detail and "consumed 700 mm" in e.value.detail
    assert scrap(db, unit, 300).unit_status == "SCRAPPED"               # SCRAP exhausted it, so SCRAPPED (not CONSUMED)
    assert state(db, unit.id) == (0, 0, 0, 700, 300, "SCRAPPED")
    assert assert_conserved(db, unit.inward_id) == 1000
    assert_unit_ok(db, unit.id)


def test_the_exhausting_movement_decides_the_terminal_status(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    scrap(db, unit, 300)                                                   # remaining 700, scrapped 300
    reserve(db, rid, alloc, 700), issue(db, rid, alloc, 700)
    assert cut(db, rid, alloc, 700).unit_remaining_length_mm == 0
    assert state(db, unit.id) == (0, 0, 0, 700, 300, "CONSUMED")           # the CUT exhausted it: CONSUMED
    assert assert_conserved(db, unit.inward_id) == 1000
    assert_unit_ok(db, unit.id)


@pytest.mark.parametrize("bad", [0, -1, 1.5, None, "abc"])
def test_scrap_schema_rejects_bad_lengths(bar, bad):
    with pytest.raises(ValidationError):
        CCScrapCreate(**_ids(bar["unit"]), length_mm=bad, reason="x", reference="y")


@pytest.mark.parametrize("bad", [0, -1, True])
def test_scrap_service_rejects_bad_lengths_without_the_schema(bar, bad):
    db, unit = bar["db"], bar["unit"]
    raw = CCScrapCreate.model_construct(**_ids(unit), length_mm=bad, reason="x", reference="y", nc_record_id=None,
                                        client_request_id=None)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Phys.scrap(db, raw, _user(db, UserRole.STORE))
    assert e.value.status_code == 400 and snapshot(db) == before


@pytest.mark.parametrize("field", ["reason", "reference"])
@pytest.mark.parametrize("bad", ["", "   ", None])
def test_scrap_and_adjustments_need_reason_and_reference(bar, field, bad):
    db, unit = bar["db"], bar["unit"]
    data = dict(**_ids(unit), length_mm=10, reason="r", reference="ref")
    data[field] = bad
    for model in (CCScrapCreate, CCAdjustmentCreate):
        with pytest.raises(ValidationError):
            model(**data)
    before = snapshot(db)
    raw = CCScrapCreate.model_construct(**data, nc_record_id=None, client_request_id=None)
    raw_adj = CCAdjustmentCreate.model_construct(**data, client_request_id=None)
    admin = _user(db, UserRole.ADMIN)
    for call in (lambda: Phys.scrap(db, raw, _user(db, UserRole.STORE)), lambda: Phys.adjust_out(db, raw_adj, admin),
                 lambda: Phys.adjust_in(db, raw_adj, admin)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 400 and field in e.value.detail
    assert snapshot(db) == before


def test_scrap_nc_pointer_is_verified_and_the_nc_record_is_never_touched(w1000):
    db, unit = w1000["db"], w1000["unit"]
    nc = NCRecord(nc_number="NC-00001", work_order_id=w1000["wo"].id, qty=1)
    db.add(nc)
    db.commit()
    nc_id, nc_rows = nc.id, rows(db, "nc_records")
    r = scrap(db, unit, 50, nc_record_id=nc_id)
    assert last_row(db).nc_record_id == nc_id and last_row(db).transaction_number == r.ledger_transaction_number
    assert rows(db, "nc_records") == nc_rows and count(db, "rejection_dispositions") == 0     # authority untouched
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        scrap(db, unit, 50, nc_record_id=uuid.uuid4())
    assert e.value.status_code == 400 and "NC record" in e.value.detail and snapshot(db) == before
    scrap(db, unit, 50)                                                    # optional: no pointer is fine
    assert last_row(db).nc_record_id is None


def test_scrap_unknown_unit_and_inward_mismatch(bar):
    db, unit = bar["db"], bar["unit"]
    (other,) = accepted_units(db, bar["mat"], [500])
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Phys.scrap(db, CCScrapCreate(stock_unit_id=uuid.uuid4(), inward_id=unit.inward_id, length_mm=1,
                                     reason="x", reference="y"), _user(db, UserRole.STORE))
    assert e.value.status_code == 404
    for bogus in (other.inward_id, uuid.uuid4()):
        with pytest.raises(HTTPException) as e:
            Phys.scrap(db, CCScrapCreate(stock_unit_id=unit.id, inward_id=bogus, length_mm=1, reason="x",
                                         reference="y"), _user(db, UserRole.STORE))
        assert e.value.status_code == 400 and "not the inward" in e.value.detail
    assert snapshot(db) == before


def test_closed_forms_reject_unknown_fields(bar):
    unit = bar["unit"]
    with pytest.raises(ValidationError):
        CCHoldCreate(**_ids(unit), reason="x", client_request_id="k")      # idempotency is only on SCRAP / ADJUSTMENT
    with pytest.raises(ValidationError):
        CCScrapCreate(**_ids(unit), length_mm=1, reason="x", reference="y", direction="OUT")
    with pytest.raises(ValidationError):
        CCAdjustmentCreate(**_ids(unit), length_mm=1, reason="x", reference="y", nc_record_id=str(uuid.uuid4()))
    with pytest.raises(ValidationError):
        CCScrapCreate(**_ids(unit), length_mm=1, reason="x", reference="y", client_request_id="  ")


# ================================================================== ADJUSTMENT_OUT
def test_adjustment_out_reduces_free_length_only(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    uid, iid = unit.id, unit.inward_id
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 300)
    allocs = rows(db, "cc_allocations")
    admin = _user(db, UserRole.ADMIN)
    before_rows = rows(db, "cc_stock_ledger")
    r = adj_out(db, unit, 40, user=admin)
    assert (r.movement_type, r.length_mm, r.unit_net_adjustment_mm) == ("ADJUSTMENT_OUT", 40, -40)
    assert state(db, uid) == (960, 300, 300, 0, 0, "IN_STOCK") and rows(db, "cc_allocations") == allocs
    assert count(db, "cc_stock_ledger") == len(before_rows) + 1
    row = last_row(db)
    assert row.movement_type == "ADJUSTMENT_OUT" and row.length_mm == 40 and row.unit_remaining_after_mm == 960
    assert row.allocation_id is None and row.related_stock_unit_id is None and row.piece_qty is None
    assert (row.reason, row.reference) == ("stock-take measured shorter", "COUNT-001")
    assert row.performed_by_id == admin.id and db.query(AuditLog).filter(AuditLog.action == "CC_ADJUSTMENT_OUT").count() == 1
    assert r.inward_accounted_length_mm == 960 == assert_conserved(db, iid)    # 1000 - 40
    assert db.query(Inward).one().received_total_length_mm == 1000             # the receipt is immutable
    assert_unit_ok(db, uid)


def test_adjustment_out_cannot_cut_into_reserved_or_issued(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 300)               # free 400
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        adj_out(db, unit, 401)
    assert e.value.status_code == 400 and "only 400 mm is free" in e.value.detail and snapshot(db) == before
    assert adj_out(db, unit, 400).unit_remaining_length_mm == 600            # exactly the boundary is allowed
    assert state(db, unit.id) == (600, 300, 300, 0, 0, "IN_STOCK")


def test_adjustment_out_can_never_exhaust_a_unit(bar):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        adj_out(db, unit, 1000)
    assert e.value.status_code == 400 and "recorded as a SCRAP" in e.value.detail and snapshot(db) == before
    assert adj_out(db, unit, 999).unit_remaining_length_mm == 1
    with pytest.raises(HTTPException):
        adj_out(db, unit, 1)                                                 # the last millimetre is not adjustable either
    assert state(db, unit.id) == (1, 0, 0, 0, 0, "IN_STOCK")


def test_adjustment_out_cannot_exhaust_a_partly_consumed_unit_either(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 700), issue(db, rid, alloc, 700), cut(db, rid, alloc, 700)    # remaining 300, free 300
    with pytest.raises(HTTPException) as e:
        adj_out(db, unit, 300)
    assert e.value.status_code == 400 and "SCRAP" in e.value.detail


@pytest.mark.parametrize("bad", [0, -1, 1.5, None])
def test_adjustment_schema_rejects_bad_lengths(bar, bad):
    with pytest.raises(ValidationError):
        CCAdjustmentCreate(**_ids(bar["unit"]), length_mm=bad, reason="x", reference="y")


@pytest.mark.parametrize("bad", [0, -1, True])
@pytest.mark.parametrize("direction", ["out", "in"])
def test_adjustment_service_rejects_bad_lengths_without_the_schema(bar, bad, direction):
    db, unit = bar["db"], bar["unit"]
    raw = CCAdjustmentCreate.model_construct(**_ids(unit), length_mm=bad, reason="x", reference="y", client_request_id=None)
    admin = _user(db, UserRole.ADMIN)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        (Phys.adjust_out if direction == "out" else Phys.adjust_in)(db, raw, admin)
    assert e.value.status_code == 400 and snapshot(db) == before


def test_adjustment_on_a_held_unit_is_allowed_and_a_terminal_unit_is_not(held_bar):
    db, unit = held_bar["db"], held_bar["unit"]
    assert adj_out(db, unit, 10).unit_status == "ON_HOLD"
    scrap(db, unit, 990)
    with pytest.raises(HTTPException) as e:
        adj_out(db, unit, 1)
    assert e.value.status_code == 400 and "terminal" in e.value.detail


# ================================================================== ADJUSTMENT_IN
def test_adjustment_in_restores_previous_adjustment_out(bar):
    db, unit = bar["db"], bar["unit"]
    uid, iid = unit.id, unit.inward_id
    adj_out(db, unit, 40)
    r = adj_in(db, unit, 25)
    assert (r.movement_type, r.unit_remaining_length_mm, r.unit_net_adjustment_mm) == ("ADJUSTMENT_IN", 985, -15)
    row = last_row(db)
    assert row.movement_type == "ADJUSTMENT_IN" and row.length_mm == 25 and row.unit_remaining_after_mm == 985
    assert row.allocation_id is None and row.related_stock_unit_id is None and row.piece_qty is None
    assert assert_conserved(db, iid) == 985                                   # 1000 - 40 + 25
    r2 = adj_in(db, unit, 15)
    assert (r2.unit_remaining_length_mm, r2.unit_net_adjustment_mm) == (1000, 0) and assert_conserved(db, iid) == 1000
    assert state(db, uid) == (1000, 0, 0, 0, 0, "IN_STOCK") and assert_unit_ok(db, uid) is None


def test_adjustment_in_cannot_exceed_the_previous_adjustment_out_total(bar):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        adj_in(db, unit, 1)                                                   # nothing was ever adjusted out
    assert e.value.status_code == 400 and "only 0 mm" in e.value.detail and snapshot(db) == before
    adj_out(db, unit, 40), adj_in(db, unit, 25)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        adj_in(db, unit, 16)                                                  # cumulative IN may not pass cumulative OUT
    assert e.value.status_code == 400 and "only 15 mm" in e.value.detail and snapshot(db) == before
    assert adj_in(db, unit, 15).unit_net_adjustment_mm == 0


def test_adjustment_in_can_never_create_length_beyond_the_receipt(bar):
    db, unit = bar["db"], bar["unit"]
    uid, iid = unit.id, unit.inward_id
    adj_out(db, unit, 50), scrap(db, unit, 100)                              # remaining 850, scrapped 100, net -50
    adj_in(db, unit, 50)
    u = fresh(db, Unit, uid)
    assert (u.remaining_length_mm, u.scrapped_length_mm) == (900, 100)
    assert u.remaining_length_mm + u.consumed_length_mm + u.scrapped_length_mm <= u.original_length_mm == 1000
    with pytest.raises(HTTPException):
        adj_in(db, unit, 1)
    assert assert_conserved(db, iid) == 1000
    c = child_of(db, split(db, fresh(db, Unit, uid), 300))                   # a remnant child has its own cap
    adj_out(db, c, 50)
    with pytest.raises(HTTPException) as e:
        adj_in(db, c, 60)
    assert e.value.status_code == 400 and "only 50 mm" in e.value.detail
    assert adj_in(db, c, 50).unit_remaining_length_mm == 300
    assert assert_conserved(db, iid) == 1000


def test_adjustment_in_guard_against_exceeding_the_original_fires_under_drift(bar):
    """Defence in depth: with a consistent ledger the cumulative cap already makes this unreachable, so the
    guard is exercised by deliberate cache drift (remaining 40 mm above what the ledger gives)."""
    db, unit = bar["db"], bar["unit"]
    adj_out(db, unit, 40)                                                    # ledger: remaining 960
    t = Base.metadata.tables["cc_stock_units"]
    db.execute(t.update().where(t.c.id == str(unit.id)).values(remaining_length_mm=1000))
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        adj_in(db, unit, 40)
    assert e.value.status_code == 400 and "would exceed the original length" in e.value.detail
    assert snapshot(db) == before


def test_the_database_still_refuses_length_beyond_the_original(bar):
    db, unit = bar["db"], bar["unit"]
    u = fresh(db, Unit, unit.id)
    u.remaining_length_mm = 1001
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    u = fresh(db, Unit, unit.id)
    u.remaining_length_mm, u.scrapped_length_mm = 600, 500
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ================================================================== the remaining formula, term by term
@pytest.mark.parametrize("totals,expected", [
    ({"INWARD": 1000}, 1000),
    ({"INWARD": 1000, "SPLIT_IN": 300}, 1300),
    ({"INWARD": 1000, "ADJUSTMENT_IN": 25}, 1025),
    ({"INWARD": 1000, "SPLIT_OUT": 300}, 700),
    ({"INWARD": 1000, "CUT_CONSUME": 200}, 800),
    ({"INWARD": 1000, "SCRAP": 100}, 900),
    ({"INWARD": 1000, "ADJUSTMENT_OUT": 40}, 960),
    ({"INWARD": 1000, "RESERVE": 500, "RELEASE": 100, "ISSUE": 400, "RETURN": 50, "HOLD": 0, "HOLD_RELEASE": 0}, 1000),
    ({"SPLIT_IN": 300, "SCRAP": 50, "ADJUSTMENT_OUT": 10, "ADJUSTMENT_IN": 5, "CUT_CONSUME": 20, "SPLIT_OUT": 25}, 200),
])
def test_each_term_of_the_remaining_formula(totals, expected):
    assert rv_svc._derive_remaining(totals) == expected == formula(totals)


def test_every_movement_applied_once_matches_the_formula(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    uid, iid = unit.id, unit.inward_id
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 400), cut(db, rid, alloc, 100)   # res 200 iss 300 con 100 rem 900
    ret(db, rid, alloc, 50), release(db, rid, alloc, 50)                                  # iss 250 res 150
    hold(db, unit), unhold(db, unit)
    split(db, fresh(db, Unit, uid), 150)                                                  # free 500 -> rem 750
    scrap(db, fresh(db, Unit, uid), 60)                                                   # rem 690, scrapped 60
    adj_out(db, fresh(db, Unit, uid), 40)                                                 # rem 650
    adj_in(db, fresh(db, Unit, uid), 15)                                                  # rem 665
    assert state(db, uid) == (665, 150, 250, 100, 60, "IN_STOCK")
    t = ledger_totals(db, uid)
    assert formula(t) == 665 == 1000 - 150 - 100 - 60 - 40 + 15
    assert assert_conserved(db, iid) == 665 + 100 + 60 + 150 - 0                          # parent + child
    for u in db.query(Unit).all():
        assert_unit_ok(db, u.id)


@pytest.mark.parametrize("what", ["remaining", "reserved", "issued", "consumed", "scrapped"])
def test_deliberate_drift_of_every_balance_is_detected_and_rolled_back(w1000, what):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600), issue(db, rid, alloc, 300), cut(db, rid, alloc, 100)     # res 300 iss 200 con 100 rem 900
    scrap(db, unit, 50)                                                                   # rem 850 scrapped 50
    u = fresh(db, Unit, unit.id)
    setattr(u, f"{what}_length_mm", getattr(u, f"{what}_length_mm") - 10)
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        hold(db, unit)
    assert e.value.status_code == 500 and "reconcil" in e.value.detail.lower() and snapshot(db) == before


@pytest.mark.parametrize("op", ["hold", "scrap", "adj_out", "split"])
def test_remaining_drift_blocks_every_new_operation(bar, op):
    db, unit = bar["db"], bar["unit"]
    fresh(db, Unit, unit.id).remaining_length_mm -= 10
    db.commit()
    before = snapshot(db)
    call = {"hold": lambda: hold(db, unit), "scrap": lambda: scrap(db, unit, 5),
            "adj_out": lambda: adj_out(db, unit, 5), "split": lambda: split(db, unit, 5)}[op]
    with pytest.raises(HTTPException) as e:
        call()
    assert e.value.status_code == 500 and snapshot(db) == before


def test_reconciliation_detects_a_ledger_that_disagrees_with_the_unit(bar):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)

    def skew(mapper, connection, target):
        if target.movement_type == "SCRAP":
            target.length_mm = target.length_mm + 1

    event.listen(Ledger, "before_insert", skew)
    try:
        with pytest.raises(HTTPException) as e:
            scrap(db, unit, 100)
    finally:
        event.remove(Ledger, "before_insert", skew)
    assert e.value.status_code == 500 and snapshot(db) == before
    assert scrap(db, unit, 100).reconciled


def test_status_reconciliation_rules(bar):
    """Corrupted statuses are detected by the reconciliation (deliberate drift, not a legitimate flow)."""
    db, unit = bar["db"], bar["unit"]
    u = fresh(db, Unit, unit.id)
    for status, fragment in (("ON_HOLD", "hold history says IN_STOCK"), ("SCRAPPED", "not exhausted by scrapping"),
                             ("CONSUMED", "not exhausted by consumption")):
        u.status = status
        with pytest.raises(HTTPException) as e:
            rv_svc._reconcile(db, u)
        assert e.value.status_code == 500 and fragment in e.value.detail
    u.status = "IN_STOCK"
    u.remaining_length_mm, u.scrapped_length_mm = 0, 0
    with pytest.raises(HTTPException) as e:
        rv_svc._reconcile(db, u)
    assert e.value.status_code == 500
    db.rollback()
    hold(db, unit)
    u = fresh(db, Unit, unit.id)
    u.status = "IN_STOCK"                                                  # the ledger says HOLD, the status says no
    with pytest.raises(HTTPException) as e:
        rv_svc._reconcile(db, u)
    assert e.value.status_code == 500 and "hold history says ON_HOLD" in e.value.detail
    db.rollback()


def test_a_live_status_on_a_unit_with_no_length_left_is_a_reconciliation_failure(bar):
    """Only the status is corrupted: remaining 0 and scrapped 1000 still agree with the ledger."""
    db, unit = bar["db"], bar["unit"]
    scrap(db, unit, 1000)
    for live in ("IN_STOCK", "ON_HOLD"):
        u = fresh(db, Unit, unit.id)
        u.status = live
        with pytest.raises(HTTPException) as e:
            rv_svc._reconcile(db, u)
        assert e.value.status_code == 500 and "no length left" in e.value.detail
        db.rollback()


def test_inward_conservation_detects_corruption(bar):
    db, unit = bar["db"], bar["unit"]
    scrap(db, unit, 100)
    inward = db.query(Inward).one()
    from app.services.continuous_casting_split_service import reconcile_inward
    assert reconcile_inward(db, inward) == 1000
    fresh(db, Unit, unit.id).scrapped_length_mm -= 0                       # unchanged: still conserved
    u = fresh(db, Unit, unit.id)
    u.remaining_length_mm -= 10
    db.flush()
    with pytest.raises(HTTPException) as e:
        reconcile_inward(db, fresh(db, Inward, inward.id))
    assert e.value.status_code == 500 and "does not conserve length" in e.value.detail
    db.rollback()


# ================================================================== conservation across every movement
def test_inward_conservation_holds_after_every_kind_of_movement(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    uid, iid = unit.id, unit.inward_id
    steps = [
        lambda: reserve(db, rid, alloc, 800), lambda: issue(db, rid, alloc, 500), lambda: hold(db, fresh(db, Unit, uid)),
        lambda: ret(db, rid, alloc, 100), lambda: unhold(db, fresh(db, Unit, uid)), lambda: cut(db, rid, alloc, 300),
        lambda: release(db, rid, alloc, 300), lambda: scrap(db, fresh(db, Unit, uid), 100),
        lambda: adj_out(db, fresh(db, Unit, uid), 40), lambda: adj_in(db, fresh(db, Unit, uid), 40),
        lambda: split(db, fresh(db, Unit, uid), 150),
    ]
    expected_after = [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 960, 1000, 1000]
    for step, exp in zip(steps, expected_after):
        step()
        assert assert_conserved(db, iid) == exp
        for u in db.query(Unit).all():
            assert_unit_ok(db, u.id)


# ================================================================== locking and stale reads
@pytest.mark.parametrize("op", ["hold", "scrap", "adj_out"])
def test_operations_lock_only_the_stock_unit(bar, monkeypatch, op):
    db, unit = bar["db"], bar["unit"]
    order = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    {"hold": lambda: hold(db, unit), "scrap": lambda: scrap(db, unit, 10), "adj_out": lambda: adj_out(db, unit, 10)}[op]()
    assert order == [Unit]


def test_issue_and_cut_still_lock_unit_allocation_routing(w1000, monkeypatch):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 500)
    order = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    issue(db, rid, alloc, 100)
    assert order == [Unit, Alloc, Routing]


def test_the_unit_is_re_read_after_the_lock(bar):
    db, unit = bar["db"], bar["unit"]
    store = _user(db, UserRole.STORE)          # users first: a commit would expire the "stale" copy
    uid, iid = unit.id, unit.inward_id
    stale = db.get(Unit, uid)
    assert stale.remaining_length_mm == 1000
    t = Base.metadata.tables["cc_stock_units"]
    db.execute(t.update().where(t.c.id == str(uid)).values(remaining_length_mm=500))
    assert stale.remaining_length_mm == 1000                                 # really stale
    with pytest.raises(HTTPException) as e:
        Phys.scrap(db, CCScrapCreate(stock_unit_id=uid, inward_id=iid, length_mm=600, reason="x", reference="y"), store)
    assert e.value.status_code == 400 and "only 500 mm is free" in e.value.detail


def test_two_connections_cannot_scrap_the_same_free_length_twice(shared):
    s1, s2 = shared
    mat = _material(s1)
    (unit,) = accepted_units(s1, mat, [1000])
    uid, iid = unit.id, unit.inward_id
    st1 = _user(s1, UserRole.STORE)
    st2 = s2.get(User, st1.id)
    stale = s2.get(Unit, uid)
    assert stale.remaining_length_mm == 1000
    Phys.scrap(s1, CCScrapCreate(stock_unit_id=uid, inward_id=iid, length_mm=600, reason="x", reference="y"), st1)
    assert stale.remaining_length_mm == 1000                                 # stale in B; truth is 400
    with pytest.raises(HTTPException) as e:
        Phys.scrap(s2, CCScrapCreate(stock_unit_id=uid, inward_id=iid, length_mm=600, reason="x", reference="y"), st2)
    assert e.value.status_code == 400 and "only 400 mm is free" in e.value.detail
    Phys.scrap(s2, CCScrapCreate(stock_unit_id=uid, inward_id=iid, length_mm=400, reason="x", reference="y"), st2)
    s1.expire_all()
    final = s1.get(Unit, uid)
    assert (final.remaining_length_mm, final.scrapped_length_mm, final.status) == (0, 1000, "SCRAPPED")
    assert assert_conserved(s1, iid) == 1000


def test_a_second_connection_cannot_hold_an_already_held_unit(shared):
    s1, s2 = shared
    mat = _material(s1)
    (unit,) = accepted_units(s1, mat, [1000])
    uid, iid = unit.id, unit.inward_id
    qa1 = _user(s1, UserRole.QA)
    qa2 = s2.get(User, qa1.id)
    stale = s2.get(Unit, uid)
    Phys.hold(s1, CCHoldCreate(stock_unit_id=uid, inward_id=iid, reason="a"), qa1)
    assert stale.status == "IN_STOCK"                                        # stale in B
    with pytest.raises(HTTPException) as e:
        Phys.hold(s2, CCHoldCreate(stock_unit_id=uid, inward_id=iid, reason="b"), qa2)
    assert e.value.status_code == 400 and "ON_HOLD" in e.value.detail
    assert s1.query(Ledger).filter_by(movement_type="HOLD").count() == 1


# ================================================================== atomicity
def _op_ready(db, unit, op):
    """Put the unit in a state where `op` is valid, and return the call."""
    for role in (UserRole.QA, UserRole.STORE, UserRole.ADMIN):
        _user(db, role)              # users first: creating one commits, which would hit a patched commit
    if op == "hold_release":
        hold(db, unit)
    if op == "adj_in":
        adj_out(db, unit, 50)
    return {"hold": lambda: hold(db, unit), "hold_release": lambda: unhold(db, unit),
            "scrap": lambda: scrap(db, unit, 100), "adj_out": lambda: adj_out(db, unit, 100),
            "adj_in": lambda: adj_in(db, unit, 30)}[op]


OPS = ["hold", "hold_release", "scrap", "adj_out", "adj_in"]


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("model_name,event_name", [("Ledger", "before_insert"), ("Unit", "after_update"),
                                                   ("AuditLog", "before_insert")])
def test_rollback_after_a_mid_transaction_failure(bar, op, model_name, event_name):
    """Ledger-insert, unit-update and audit failures leave nothing behind, for every operation."""
    db, unit = bar["db"], bar["unit"]
    call = _op_ready(db, unit, op)
    model = {"Ledger": Ledger, "Unit": Unit, "AuditLog": AuditLog}[model_name]
    before = snapshot(db)
    off = _raising_listener(model, event_name)
    try:
        with pytest.raises(RuntimeError):
            call()
    finally:
        off()
    assert snapshot(db) == before
    assert call().reconciled                                               # and a retry is clean
    assert_unit_ok(db, unit.id)


@pytest.mark.parametrize("op", OPS)
def test_commit_time_failure_rolls_everything_back(bar, monkeypatch, op):
    db, unit = bar["db"], bar["unit"]
    call = _op_ready(db, unit, op)
    before = snapshot(db)
    seen = {}

    def failing_commit():
        seen["rows"] = count(db, "cc_stock_ledger")
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        call()
    monkeypatch.undo()
    assert seen["rows"] == len(before["cc_stock_ledger"]) + 1               # the row WAS in the transaction
    assert snapshot(db) == before


def test_rollback_after_everything_was_flushed(bar, monkeypatch):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)

    def late(*a, **k):
        raise RuntimeError("late failure")

    monkeypatch.setattr(ph_svc, "CCUnitMovementResult", late)
    with pytest.raises(RuntimeError):
        scrap(db, unit, 100)
    assert snapshot(db) == before


def test_ledger_number_collision_is_retried_and_recovers(bar, monkeypatch):
    db, unit = bar["db"], bar["unit"]
    taken, real, calls = db.query(Ledger).one().transaction_number, ph_svc.next_cc_ledger_transaction_number, []

    def fake(session):
        calls.append(1)
        return taken if len(calls) == 1 else real(session)

    monkeypatch.setattr(ph_svc, "next_cc_ledger_transaction_number", fake)
    r = scrap(db, unit, 100)
    assert len(calls) == 2 and r.ledger_transaction_number != taken
    assert db.query(Ledger).filter_by(movement_type="SCRAP").count() == 1


def test_persistent_collision_is_a_controlled_409_with_nothing_changed(bar, monkeypatch):
    db, unit = bar["db"], bar["unit"]
    taken = db.query(Ledger).one().transaction_number
    before = snapshot(db)
    monkeypatch.setattr(ph_svc, "next_cc_ledger_transaction_number", lambda session: taken)
    with pytest.raises(HTTPException) as e:
        hold(db, unit)
    assert e.value.status_code == 409 and snapshot(db) == before


# ================================================================== idempotency (SCRAP and ADJUSTMENT only)
def test_scrap_replay_with_the_same_key_does_not_scrap_twice(bar):
    db, unit = bar["db"], bar["unit"]
    first = scrap(db, unit, 100, client_request_id="REQ-1")
    rows_after_first = count(db, "cc_stock_ledger")
    again = scrap(db, unit, 100, client_request_id="REQ-1")
    assert again.replayed is True and first.replayed is False
    assert again.ledger_transaction_number == first.ledger_transaction_number
    assert count(db, "cc_stock_ledger") == rows_after_first and state(db, unit.id) == (900, 0, 0, 0, 100, "IN_STOCK")
    assert last_row(db).client_request_id == "REQ-1" and "already recorded" in again.message
    assert_unit_ok(db, unit.id)


@pytest.mark.parametrize("op", ["adj_out", "adj_in"])
def test_adjustment_replay_with_the_same_key(bar, op):
    db, unit = bar["db"], bar["unit"]
    if op == "adj_in":
        adj_out(db, unit, 100)
    fn = adj_out if op == "adj_out" else adj_in
    a = fn(db, unit, 40, client_request_id="ADJ-1")
    n = count(db, "cc_stock_ledger")
    b = fn(db, unit, 40, client_request_id="ADJ-1")
    assert b.replayed and b.ledger_transaction_number == a.ledger_transaction_number and count(db, "cc_stock_ledger") == n
    assert b.unit_remaining_length_mm == a.unit_remaining_length_mm


def test_a_reused_key_for_a_different_request_is_a_409(bar):
    db, unit = bar["db"], bar["unit"]
    (other,) = accepted_units(db, bar["mat"], [500])
    scrap(db, unit, 100, client_request_id="REQ-2")
    before = snapshot(db)
    for call in (lambda: scrap(db, unit, 50, client_request_id="REQ-2"),          # different length
                 lambda: adj_out(db, unit, 100, client_request_id="REQ-2"),       # different movement
                 lambda: scrap(db, other, 100, client_request_id="REQ-2")):       # different unit
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 409
    assert snapshot(db) == before


def test_a_missing_key_is_safe_and_repeats_are_independent(bar):
    db, unit = bar["db"], bar["unit"]
    scrap(db, unit, 100), scrap(db, unit, 100)                              # no key: two separate movements
    assert db.query(Ledger).filter_by(movement_type="SCRAP").count() == 2
    assert [r.client_request_id for r in db.query(Ledger).filter_by(movement_type="SCRAP")] == [None, None]
    assert state(db, unit.id) == (800, 0, 0, 0, 200, "IN_STOCK")


def test_two_requests_racing_on_one_key_are_retried_into_a_replay(bar, monkeypatch):
    db, unit = bar["db"], bar["unit"]
    scrap(db, unit, 100, client_request_id="REQ-3")
    calls = []
    real_apply = ph_svc._apply

    def racing_apply(session, kind, req, user):
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed: cc_stock_ledger.client_request_id"))
        return real_apply(session, kind, req, user)

    monkeypatch.setattr(ph_svc, "_apply", racing_apply)
    r = scrap(db, unit, 100, client_request_id="REQ-3")
    assert len(calls) == 2 and r.replayed is True
    assert state(db, unit.id) == (900, 0, 0, 0, 100, "IN_STOCK")


# ================================================================== randomized legitimate sequence
def test_random_legitimate_sequences_keep_every_invariant(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    (root,) = accepted_units(db, mat, [1000])
    iid = root.inward_id
    rid0 = new_routing(db, mat)
    units = [root.id]
    book = {root.id: (rid0, allocate(db, rid0, root, 1000))}
    rng = random.Random(9)
    kinds = ["reserve", "issue", "cut", "return", "release", "split", "hold", "unhold", "scrap", "adj_out", "adj_in"]
    ok = {k: 0 for k in kinds}
    rejected = 0
    seq = 0
    for step in range(480):
        uid, op = rng.choice(units), rng.choice(kinds)
        u, a = fresh(db, Unit, uid), fresh(db, Alloc, book[uid][1].id)
        free_len = u.remaining_length_mm - u.reserved_length_mm - u.issued_length_mm
        room = {"reserve": free_len, "issue": a.reserved_length_mm, "cut": a.issued_length_mm,
                "return": a.issued_length_mm, "release": a.reserved_length_mm, "split": free_len,
                "scrap": free_len, "adj_out": free_len, "adj_in": 60, "hold": 1, "unhold": 1}[op]
        x = rng.randint(1, max(1, room)) if rng.random() < 0.85 else rng.randint(1, 300)
        if op in ("scrap", "adj_out", "adj_in") and rng.random() < 0.8:
            x = rng.randint(1, max(1, min(room, 120)))                       # keep units alive longer
        rid, alloc = book[uid]
        try:
            if op == "split":
                r = split(db, u, x)
                child = child_of(db, r)
                units.append(child.id)
                seq += 1
                make_wo(db, f"WO-R{seq}")
                crid = new_routing(db, mat, f"WO-R{seq}")
                book[child.id] = (crid, allocate(db, crid, child, child.remaining_length_mm))
            elif op == "hold":
                hold(db, u)
            elif op == "unhold":
                unhold(db, u)
            elif op == "scrap":
                scrap(db, u, x)
            elif op == "adj_out":
                adj_out(db, u, x)
            elif op == "adj_in":
                adj_in(db, u, x)
            else:
                {"reserve": reserve, "issue": issue, "cut": cut, "return": ret, "release": release}[op](db, rid, alloc, x)
            ok[op] += 1
        except HTTPException as e:
            assert e.status_code == 400, e.detail
            rejected += 1
            continue
        for u_id in units:
            assert_unit_ok(db, u_id)
            cu = fresh(db, Unit, u_id)
            assert min(cu.remaining_length_mm, cu.reserved_length_mm, cu.issued_length_mm, cu.consumed_length_mm,
                       cu.scrapped_length_mm) >= 0
            assert cu.reserved_length_mm + cu.issued_length_mm <= cu.remaining_length_mm
            ca = fresh(db, Alloc, book[u_id][1].id)
            assert ca.reserved_length_mm + ca.issued_length_mm + ca.consumed_length_mm <= ca.planned_length_mm
        assert_conserved(db, iid)
    assert all(n > 0 for n in ok.values()), ok
    assert ok["split"] >= 3 and rejected > 40
    assert db.query(Inward).one().received_piece_count == 1
