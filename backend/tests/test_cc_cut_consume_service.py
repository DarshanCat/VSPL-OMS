"""Continuous Casting CUT_CONSUME (Phase 6). In-memory SQLite only; no database file is created.

Reuses the Phase 4/5 fixtures and helpers. SQLite ignores FOR UPDATE, so PostgreSQL row-lock
behaviour is not proven here; the lock request/order, the fresh re-read (two real connections),
and the transactional + CHECK invariants are.
"""
import random
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query

from app.core.database import Base
from app.models import *  # noqa: F401,F403
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WOStatus
from app.schemas.continuous_casting import CCCutConsumeCreate, CCIssueCreate, CCReserveCreate, CCRoutingReleaseCreate
import app.services.continuous_casting_reservation_service as rv_svc
from app.services.continuous_casting_reservation_service import ContinuousCastingReservationService as Rsv

from test_cc_reservation_service import (  # noqa: F401
    db, shared, world, Ledger, Alloc, Unit, Routing, Inward,
    _user, make_wo, _material, accepted_units, new_routing, supersede, allocate, reserve, release,
    simulate_issue, _ledger_row, count, rows, oms_state, snapshot, fresh, ledger_totals,
    assert_reconciled, _raising_listener, _flaky,
)
from test_cc_issue_service import issue  # noqa: F401


def cut(db, rid, alloc, x, user=None, unit_id=None, **kw):
    return Rsv.cut_consume(
        db, CCCutConsumeCreate(routing_id=rid, allocation_id=alloc.id, length_mm=x,
                               stock_unit_id=unit_id or alloc.stock_unit_id, **kw),
        user or _user(db, UserRole.PRODUCTION_MANAGER))


@pytest.fixture()
def w1000(db):
    mat = _material(db)
    wo = make_wo(db, "WO-1001")
    (unit,) = accepted_units(db, mat, [1000])
    rid = new_routing(db, mat)
    return dict(db=db, mat=mat, wo=wo, unit=unit, rid=rid, alloc=allocate(db, rid, unit, 1000))


@pytest.fixture()
def issued1000(w1000):
    """1000 mm unit, plan 1000, all of it reserved and issued."""
    reserve(w1000["db"], w1000["rid"], w1000["alloc"], 1000)
    issue(w1000["db"], w1000["rid"], w1000["alloc"], 1000)
    return w1000


@pytest.fixture()
def mixed(w1000):
    """Reserved 400 and issued 600 on the same allocation."""
    reserve(w1000["db"], w1000["rid"], w1000["alloc"], 1000)
    issue(w1000["db"], w1000["rid"], w1000["alloc"], 600)
    return w1000


def two_allocations(db):
    """One unit shared by two WOs: allocation a1 has 300 issued, a2 has 200 issued (unit issued 500)."""
    mat = _material(db)
    make_wo(db, "WO-1001")
    make_wo(db, "WO-1002")
    (unit,) = accepted_units(db, mat, [1000])
    r1, r2 = new_routing(db, mat), new_routing(db, mat, "WO-1002")
    a1, a2 = allocate(db, r1, unit, 500), allocate(db, r2, unit, 500)
    reserve(db, r1, a1, 300), issue(db, r1, a1, 300)
    reserve(db, r2, a2, 200), issue(db, r2, a2, 200)
    return dict(db=db, mat=mat, unit=unit, r1=r1, a1=a1, r2=r2, a2=a2)


# ------------------------------------------------------------------ the semantic rule
def test_issued_1000_consume_300(issued1000):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    r = cut(db, rid, alloc, 300)
    assert r.movement_type == "CUT_CONSUME" and r.length_mm == 300 and r.reconciled is True
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (700, 300, 700)
    assert r.unit_reserved_length_mm == 0
    assert (r.allocation_issued_length_mm, r.allocation_consumed_length_mm, r.allocation_reserved_length_mm) == (700, 300, 0)
    assert r.allocation_status == "PARTIALLY_CONSUMED" and r.ledger_transaction_number == "TXN-000004"
    assert "consumed" in r.message
    assert_reconciled(db, unit)


def test_reserved_length_is_not_touched_by_a_cut(mixed):
    db, unit, alloc, rid = mixed["db"], mixed["unit"], mixed["alloc"], mixed["rid"]
    r = cut(db, rid, alloc, 300)
    assert (r.unit_reserved_length_mm, r.allocation_reserved_length_mm) == (400, 400)       # unchanged
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (300, 300, 700)
    assert r.unit_free_length_mm == 0                                    # (700 - 400 - 300): free length unchanged too
    assert_reconciled(db, unit)


def test_consuming_the_entire_issued_balance(issued1000):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    r = cut(db, rid, alloc, 1000)
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (0, 1000, 0)
    assert r.allocation_status == "CONSUMED"                              # consumed == planned
    assert fresh(db, Unit, unit.id).status == "CONSUMED"                  # nothing physical is left
    assert_reconciled(db, unit)


def test_consuming_all_issued_while_a_reservation_remains(mixed):
    db, unit, alloc, rid = mixed["db"], mixed["unit"], mixed["alloc"], mixed["rid"]
    r = cut(db, rid, alloc, 600)
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (0, 600, 400)
    assert (r.unit_reserved_length_mm, r.allocation_status) == (400, "PARTIALLY_CONSUMED")
    assert fresh(db, Unit, unit.id).status == "IN_STOCK"                  # 400 mm still on the bar
    with pytest.raises(HTTPException) as e:                               # the reservation is not cuttable
        cut(db, rid, alloc, 1)
    assert e.value.status_code == 400 and "must be issued first" in e.value.detail


def test_partial_consumption_leaves_the_right_issued_balance_for_later(issued1000):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    for x, issued_left, consumed in ((250, 750, 250), (250, 500, 500), (100, 400, 600)):
        r = cut(db, rid, alloc, x)
        assert (r.allocation_issued_length_mm, r.allocation_consumed_length_mm) == (issued_left, consumed)
        assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == \
            (issued_left, consumed, 1000 - consumed)
        assert_reconciled(db, unit)
    assert cut(db, rid, alloc, 400).allocation_issued_length_mm == 0     # the rest is still cuttable


def test_cutting_reserved_only_material_is_rejected(w1000):
    db, alloc, rid = w1000["db"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600)                                          # reserved, never issued
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        cut(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "Only ISSUED material can be cut" in e.value.detail
    assert snapshot(db) == before


# ------------------------------------------------------------------ amounts
def test_cannot_cut_more_than_the_unit_issued_balance(db):
    w = two_allocations(db)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        cut(db, w["r1"], w["a1"], 501)                                    # unit issued is 300 + 200 = 500
    assert e.value.status_code == 400 and "stock unit" in e.value.detail and "only 500 mm" in e.value.detail
    assert snapshot(db) == before


def test_cannot_cut_more_than_the_allocation_issued_balance(db):
    w = two_allocations(db)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        cut(db, w["r1"], w["a1"], 400)                                    # unit has 500 issued, but a1 only 300
    assert e.value.status_code == 400 and "only 300 mm is issued on allocation" in e.value.detail
    assert snapshot(db) == before
    assert cut(db, w["r1"], w["a1"], 300).allocation_issued_length_mm == 0
    assert fresh(db, Alloc, w["a2"].id).issued_length_mm == 200           # the other WO's issue is untouched
    assert_reconciled(db, w["unit"])


@pytest.mark.parametrize("bad", [0, -5, 1.5, None, "abc"])
def test_schema_rejects_zero_negative_and_non_integer_lengths(issued1000, bad):
    with pytest.raises(ValidationError):
        CCCutConsumeCreate(routing_id=issued1000["rid"], allocation_id=issued1000["alloc"].id,
                           stock_unit_id=issued1000["alloc"].stock_unit_id, length_mm=bad)


@pytest.mark.parametrize("bad", [0, -1, True])
def test_service_rejects_bad_lengths_without_schema_validation(issued1000, bad):
    db, alloc = issued1000["db"], issued1000["alloc"]
    raw = CCCutConsumeCreate.model_construct(routing_id=issued1000["rid"], allocation_id=alloc.id,
                                             stock_unit_id=alloc.stock_unit_id, length_mm=bad, reason=None)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Rsv.cut_consume(db, raw, _user(db, UserRole.PRODUCTION_MANAGER))
    assert e.value.status_code == 400 and snapshot(db) == before


def test_no_silent_rounding_the_length_is_taken_exactly(issued1000):
    db, alloc, rid = issued1000["db"], issued1000["alloc"], issued1000["rid"]
    r = cut(db, rid, alloc, 333)
    assert r.length_mm == 333 and r.unit_consumed_length_mm == 333 and r.unit_remaining_length_mm == 667


# ------------------------------------------------------------------ identity: routing / allocation / unit
def test_identity_fields_are_required(issued1000):
    db, alloc, rid = issued1000["db"], issued1000["alloc"], issued1000["rid"]
    for missing in ("routing_id", "allocation_id", "stock_unit_id"):
        data = dict(routing_id=rid, allocation_id=alloc.id, stock_unit_id=alloc.stock_unit_id, length_mm=10)
        del data[missing]
        with pytest.raises(ValidationError):
            CCCutConsumeCreate(**data)
        data[missing], data["reason"] = None, None
        with pytest.raises(HTTPException) as e:
            Rsv.cut_consume(db, CCCutConsumeCreate.model_construct(**data, ), _user(db, UserRole.PRODUCTION_MANAGER))
        assert e.value.status_code == 400 and "required" in e.value.detail


def test_mismatched_allocation_is_rejected(issued1000):
    db, rid = issued1000["db"], issued1000["rid"]
    make_wo(db, "WO-1002")
    other_rid = new_routing(db, issued1000["mat"], "WO-1002")
    (u2,) = accepted_units(db, issued1000["mat"], [500])
    other = allocate(db, other_rid, u2, 500)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:                               # another WO's allocation, this routing
        cut(db, rid, other, 10)
    assert e.value.status_code == 400 and "does not belong" in e.value.detail
    with pytest.raises(HTTPException) as e:
        Rsv.cut_consume(db, CCCutConsumeCreate(routing_id=rid, allocation_id=uuid.uuid4(),
                                               stock_unit_id=u2.id, length_mm=10),
                        _user(db, UserRole.PRODUCTION_MANAGER))
    assert e.value.status_code == 404 and snapshot(db) == before


def test_mismatched_stock_unit_is_rejected(issued1000):
    db, alloc, rid = issued1000["db"], issued1000["alloc"], issued1000["rid"]
    (other,) = accepted_units(db, issued1000["mat"], [900])
    before = snapshot(db)
    for bogus in (other.id, uuid.uuid4()):
        with pytest.raises(HTTPException) as e:
            cut(db, rid, alloc, 100, unit_id=bogus)
        assert e.value.status_code == 400 and "not the unit allocated" in e.value.detail
    assert snapshot(db) == before


def test_mismatched_routing_is_rejected(issued1000):
    db, alloc = issued1000["db"], issued1000["alloc"]
    make_wo(db, "WO-1002")
    other_rid = new_routing(db, issued1000["mat"], "WO-1002")
    before = snapshot(db)
    for bogus in (uuid.uuid4(), other_rid):
        with pytest.raises(HTTPException) as e:
            cut(db, bogus, alloc, 100)
        assert e.value.status_code == 400 and "does not belong" in e.value.detail
    assert snapshot(db) == before


# ------------------------------------------------------------------ routing / work-order lifecycle
def test_superseded_routing_cannot_cut(issued1000):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    supersede(db, issued1000["mat"])
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        cut(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "SUPERSEDED" in e.value.detail and "cutting" in e.value.detail
    assert snapshot(db) == before                                         # issued stock stays issued
    assert_reconciled(db, unit)


def test_cut_follows_the_same_routing_rule_as_reserve_and_issue(mixed):
    db, alloc, rid = mixed["db"], mixed["alloc"], mixed["rid"]
    for state in ("DRAFT", "SUPERSEDED"):
        db.query(Routing).one().status = state
        db.commit()
        for op in (lambda: cut(db, rid, alloc, 10), lambda: issue(db, rid, alloc, 10),
                   lambda: reserve(db, rid, alloc, 10)):
            with pytest.raises(HTTPException) as e:
                op()
            assert e.value.status_code == 400 and state in e.value.detail


def test_non_continuous_casting_routing_cannot_cut(issued1000):
    db = issued1000["db"]
    db.query(Routing).one().material_source = "F1_PRODUCTION"
    db.commit()
    with pytest.raises(HTTPException) as e:
        cut(db, issued1000["rid"], issued1000["alloc"], 10)
    assert e.value.status_code == 400 and "CONTINUOUS_CASTING" in e.value.detail


@pytest.mark.parametrize("state", [WOStatus.CLOSED, WOStatus.DISPATCHED])
def test_closed_work_order_cannot_cut(issued1000, state):
    db = issued1000["db"]
    fresh(db, WorkOrder, issued1000["wo"].id).status = state
    db.commit()
    with pytest.raises(HTTPException) as e:
        cut(db, issued1000["rid"], issued1000["alloc"], 10)
    assert e.value.status_code == 400


def test_already_fully_consumed_unit_is_rejected(issued1000):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    cut(db, rid, alloc, 1000)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        cut(db, rid, alloc, 1)
    assert e.value.status_code == 400 and "already fully consumed" in e.value.detail
    assert snapshot(db) == before


def test_a_unit_marked_consumed_is_rejected_even_with_length_left(issued1000):
    db, unit = issued1000["db"], issued1000["unit"]
    fresh(db, Unit, unit.id).status = "CONSUMED"
    db.commit()
    with pytest.raises(HTTPException) as e:
        cut(db, issued1000["rid"], issued1000["alloc"], 10)
    assert e.value.status_code == 400 and "already fully consumed" in e.value.detail


# ------------------------------------------------------------------ physical length and pieces
def test_raw_length_leaves_the_bar_exactly_and_nothing_else_changes(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    u1, u2 = accepted_units(db, mat, [1000, 1500])
    rid = new_routing(db, mat)
    a1, a2 = allocate(db, rid, u1, 1000), allocate(db, rid, u2, 800)
    for a in (a1, a2):
        reserve(db, rid, a, a.planned_length_mm)
        issue(db, rid, a, a.planned_length_mm)
    other_before = rows(db, "cc_stock_units")
    other_before = [r for r in other_before if str(r[0]) == str(u2.id)]
    inward_before = rows(db, "cc_inwards")
    for x in (300, 200, 150):
        cut(db, rid, a1, x)
        unit = fresh(db, Unit, u1.id)
        assert unit.original_length_mm == 1000                            # identity of the bar never rewritten
        assert unit.remaining_length_mm + unit.consumed_length_mm == unit.original_length_mm
    assert fresh(db, Unit, u1.id).remaining_length_mm == 350
    assert [r for r in rows(db, "cc_stock_units") if str(r[0]) == str(u2.id)] == other_before   # other bar untouched
    assert rows(db, "cc_inwards") == inward_before                        # header totals untouched


def test_physical_piece_count_is_not_changed_or_made_fractional(issued1000):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    inward_before = rows(db, "cc_inwards")
    units_before = count(db, "cc_stock_units")
    for x in (333, 111, 1):
        r = cut(db, rid, alloc, x)
        row = db.query(Ledger).filter_by(transaction_number=r.ledger_transaction_number).one()
        assert row.piece_qty is None                                       # a length event, not a piece event
    inward = db.query(Inward).one()
    assert inward.received_piece_count == 1 and type(inward.received_piece_count) is int
    assert rows(db, "cc_inwards") == inward_before and count(db, "cc_stock_units") == units_before
    u = fresh(db, Unit, unit.id)
    for value in (u.original_length_mm, u.remaining_length_mm, u.reserved_length_mm, u.issued_length_mm,
                  u.consumed_length_mm):
        assert type(value) is int                                          # whole millimetres only


# ------------------------------------------------------------------ ledger
def test_exactly_one_correct_immutable_cut_consume_row(issued1000):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    before, issues_before = count(db, "cc_stock_ledger"), db.query(Ledger).filter_by(movement_type="ISSUE").count()
    user = _user(db, UserRole.PRODUCTION_MANAGER)
    r = cut(db, rid, alloc, 300, user=user, reason="Cut for WO-1001 blanks")
    assert count(db, "cc_stock_ledger") == before + 1
    assert db.query(Ledger).filter_by(movement_type="ISSUE").count() == issues_before    # no hidden second row
    row = db.query(Ledger).filter_by(transaction_number=r.ledger_transaction_number).one()
    assert row.movement_type == "CUT_CONSUME" and row.length_mm == 300 and row.piece_qty is None
    assert row.inward_id == unit.inward_id and row.stock_unit_id == unit.id and row.allocation_id == alloc.id
    assert row.unit_remaining_after_mm == 700                                # the length that is left after the cut
    assert row.performed_by_id == user.id and row.performed_by_name == user.full_name
    assert row.reason == "Cut for WO-1001 blanks" and row.client_request_id is None and row.created_at is not None
    assert alloc.allocation_number in row.reference and "WO-1001" in row.reference and "routing v1" in row.reference
    assert db.get(Routing, db.get(Alloc, row.allocation_id).routing_id).work_order.wo_number == "WO-1001"
    assert db.query(AuditLog).filter(AuditLog.action == "CC_CUT_CONSUME").one().entity_id == alloc.allocation_number
    row.reason = "tamper"
    with pytest.raises(ValueError):
        db.flush()
    db.rollback()


def test_default_reason(issued1000):
    r = cut(issued1000["db"], issued1000["rid"], issued1000["alloc"], 10)
    assert "Cut consumption for WO-1001 routing v1" in issued1000["db"].query(Ledger).filter_by(
        transaction_number=r.ledger_transaction_number).one().reason


# ------------------------------------------------------------------ sequences + reconciliation
def test_issue_then_cut_gives_the_right_balances(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600)
    issue(db, rid, alloc, 400)
    r = cut(db, rid, alloc, 250)
    assert (r.unit_remaining_length_mm, r.unit_reserved_length_mm, r.unit_issued_length_mm,
            r.unit_consumed_length_mm) == (750, 200, 150, 250)
    assert (r.allocation_reserved_length_mm, r.allocation_issued_length_mm, r.allocation_consumed_length_mm,
            r.allocation_planned_length_mm) == (200, 150, 250, 1000)
    assert_reconciled(db, unit)


def test_several_issue_and_cut_operations_on_one_allocation(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 1000)
    steps = [("issue", 300), ("cut", 100), ("issue", 200), ("cut", 250), ("cut", 150), ("issue", 500), ("cut", 500)]
    for op, x in steps:
        (issue if op == "issue" else cut)(db, rid, alloc, x)
        assert_reconciled(db, unit)                                        # after EVERY successful operation
    u, a = fresh(db, Unit, unit.id), fresh(db, Alloc, alloc.id)
    assert (u.reserved_length_mm, u.issued_length_mm, u.consumed_length_mm, u.remaining_length_mm) == (0, 0, 1000, 0)
    assert a.consumed_length_mm == 1000 and a.status == "CONSUMED" and u.status == "CONSUMED"
    t = ledger_totals(db, unit.id)
    assert t["CUT_CONSUME"] == 1000 and t["ISSUE"] == 1000 and t["RESERVE"] == 1000


@pytest.mark.parametrize("what", ["unit_issued", "unit_consumed", "alloc_issued", "alloc_consumed"])
def test_deliberate_cache_drift_is_detected_and_rolled_back(issued1000, what):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    cut(db, rid, alloc, 100)                                               # issued 900, consumed 100, remaining 900
    u, a = fresh(db, Unit, unit.id), fresh(db, Alloc, alloc.id)
    if what == "unit_issued":
        u.issued_length_mm -= 50
    elif what == "unit_consumed":
        u.consumed_length_mm -= 50
    elif what == "alloc_issued":
        a.issued_length_mm -= 50
    else:
        a.consumed_length_mm -= 50
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        cut(db, rid, alloc, 100)
    assert e.value.status_code == 500 and "reconcil" in e.value.detail.lower()
    assert snapshot(db) == before                                          # no partial change survived


def test_a_ledger_that_disagrees_with_the_balances_rolls_everything_back(issued1000):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    before = snapshot(db)

    def skew(mapper, connection, target):
        target.length_mm = target.length_mm + 1

    event.listen(Ledger, "before_insert", skew)
    try:
        with pytest.raises(HTTPException) as e:
            cut(db, rid, alloc, 100)
    finally:
        event.remove(Ledger, "before_insert", skew)
    assert e.value.status_code == 500 and snapshot(db) == before
    assert cut(db, rid, alloc, 100).reconciled is True


def test_reconciliation_still_holds_with_a_later_return_in_the_ledger(issued1000):
    """RETURN arrives in a later phase; its formula term already reconciles, and cutting still works."""
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    cut(db, rid, alloc, 300)
    u, a = fresh(db, Unit, unit.id), fresh(db, Alloc, alloc.id)
    u.issued_length_mm -= 100
    a.issued_length_mm -= 100
    _ledger_row(db, u, a, "RETURN", 100)
    db.commit()
    assert_reconciled(db, unit)
    r = cut(db, rid, alloc, 200)
    assert r.reconciled is True and (r.unit_issued_length_mm, r.unit_consumed_length_mm) == (400, 500)
    assert_reconciled(db, unit)


def test_the_database_check_constraints_still_back_the_cut_up(issued1000):
    db, unit = issued1000["db"], issued1000["unit"]
    u = fresh(db, Unit, unit.id)
    u.consumed_length_mm = u.original_length_mm + 1                         # remaining + consumed > original
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ------------------------------------------------------------------ plan guard (no fabricated data)
@pytest.mark.parametrize("reserved,issued,consumed,x,planned,exceeds", [
    (0, 600, 0, 600, 600, False), (400, 600, 0, 300, 1000, False), (0, 1000, 0, 1000, 1000, False),
    (400, 600, 100, 300, 1000, True), (0, 600, 100, 600, 600, True), (601, 0, 0, 0, 600, True),
    (0, 0, 600, 0, 600, False), (200, 100, 300, 100, 600, False),
])
def test_cut_plan_predicate(reserved, issued, consumed, x, planned, exceeds):
    alloc = SimpleNamespace(reserved_length_mm=reserved, issued_length_mm=issued,
                            consumed_length_mm=consumed, planned_length_mm=planned)
    assert rv_svc._cut_would_exceed_plan(alloc, x) is exceeds


def test_cut_consults_the_plan_rule(issued1000, monkeypatch):
    db, alloc, rid = issued1000["db"], issued1000["alloc"], issued1000["rid"]
    before = snapshot(db)
    monkeypatch.setattr(rv_svc, "_cut_would_exceed_plan", lambda allocation, length: True)
    with pytest.raises(HTTPException) as e:
        cut(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "exceed the planned 1000" in e.value.detail and snapshot(db) == before
    monkeypatch.undo()
    assert cut(db, rid, alloc, 100).success


def test_a_cut_is_a_pure_transfer_so_the_plan_total_never_changes(mixed):
    db, alloc, rid = mixed["db"], mixed["alloc"], mixed["rid"]
    total = lambda: (lambda a: a.reserved_length_mm + a.issued_length_mm + a.consumed_length_mm)(fresh(db, Alloc, alloc.id))
    before = total()
    for x in (100, 200, 300):
        cut(db, rid, alloc, x)
        assert total() == before == 1000


# ------------------------------------------------------------------ roles
@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.PRODUCTION_MANAGER])
def test_cut_roles_allowed(issued1000, role):
    db = issued1000["db"]
    assert cut(db, issued1000["rid"], issued1000["alloc"], 100, user=_user(db, role)).success


@pytest.mark.parametrize("role", [UserRole.STORE, UserRole.PLANNER, UserRole.ENGINEERING, UserRole.QA,
                                  UserRole.DISPATCH, UserRole.CEO, UserRole.MACHINE_OPERATOR])
def test_other_roles_cannot_cut(issued1000, role):
    db = issued1000["db"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        cut(db, issued1000["rid"], issued1000["alloc"], 100, user=_user(db, role))
    assert e.value.status_code == 403 and snapshot(db) == before


def test_each_stock_step_belongs_to_its_own_role(world):
    """Planner reserves, Store issues, Production Manager cuts; nobody can do the neighbouring step."""
    db, alloc, rid = world["db"], world["alloc"], world["rid"]
    planner, store, pm = (_user(db, r) for r in (UserRole.PLANNER, UserRole.STORE, UserRole.PRODUCTION_MANAGER))
    reserve(db, rid, alloc, 600, user=planner)
    issue(db, rid, alloc, 600, user=store)
    cut(db, rid, alloc, 100, user=pm)
    for op in (lambda: reserve(db, rid, alloc, 1, user=pm), lambda: issue(db, rid, alloc, 1, user=pm),
               lambda: cut(db, rid, alloc, 1, user=store), lambda: cut(db, rid, alloc, 1, user=planner)):
        with pytest.raises(HTTPException) as e:
            op()
        assert e.value.status_code == 403


def test_anonymous_cannot_cut(issued1000):
    alloc = issued1000["alloc"]
    with pytest.raises(HTTPException) as e:
        Rsv.cut_consume(issued1000["db"], CCCutConsumeCreate(routing_id=issued1000["rid"], allocation_id=alloc.id,
                                                             stock_unit_id=alloc.stock_unit_id, length_mm=10), None)
    assert e.value.status_code == 403


# ------------------------------------------------------------------ QA follows the established lifecycle
@pytest.mark.parametrize("qa", ["PENDING_QA", "REJECTED", "ON_HOLD"])
def test_a_later_qa_change_does_not_block_cutting_issued_material(issued1000, qa):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    db.query(Inward).one().qa_status = qa
    db.commit()
    r = cut(db, rid, alloc, 300)
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (700, 300, 700)
    assert fresh(db, Inward, unit.inward_id).qa_status == qa              # QA is neither read nor written by a cut
    assert_reconciled(db, unit)
    with pytest.raises(HTTPException):                                     # new reservations still need ACCEPTED
        reserve(db, rid, alloc, 1)


def test_no_china_qa_workflow_is_introduced(issued1000):
    assert "qa_status" not in CCCutConsumeCreate.model_fields
    with pytest.raises(ValidationError):
        CCCutConsumeCreate(routing_id=issued1000["rid"], allocation_id=issued1000["alloc"].id,
                           stock_unit_id=issued1000["alloc"].stock_unit_id, length_mm=10, qa_status="ACCEPTED")
    with pytest.raises(ValidationError):
        CCCutConsumeCreate(routing_id=issued1000["rid"], allocation_id=issued1000["alloc"].id,
                           stock_unit_id=issued1000["alloc"].stock_unit_id, length_mm=10, client_request_id="x")


# ------------------------------------------------------------------ locking + stale reads
def test_cut_locks_unit_then_allocation_then_routing(issued1000, monkeypatch):
    order = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    cut(issued1000["db"], issued1000["rid"], issued1000["alloc"], 100)
    assert order == [Unit, Alloc, Routing]


def test_balances_are_re_read_after_the_lock(issued1000):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    pm = _user(db, UserRole.PRODUCTION_MANAGER)    # created BEFORE caching: creating a user commits, and a commit
    #                                                expires every cached object, which would silently un-stale them
    stale_u, stale_a = db.get(Unit, unit.id), db.get(Alloc, alloc.id)       # BOTH cached, so both can go stale
    assert (stale_u.issued_length_mm, stale_a.issued_length_mm) == (1000, 1000)
    a_t, u_t = Base.metadata.tables["cc_allocations"], Base.metadata.tables["cc_stock_units"]
    db.execute(a_t.update().where(a_t.c.id == str(alloc.id)).values(issued_length_mm=100, consumed_length_mm=900))
    db.execute(u_t.update().where(u_t.c.id == str(unit.id)).values(issued_length_mm=100, consumed_length_mm=900,
                                                                   remaining_length_mm=100))
    assert (stale_u.issued_length_mm, stale_a.issued_length_mm) == (1000, 1000)   # the ORM copies really are stale
    with pytest.raises(HTTPException) as e:
        cut(db, rid, alloc, 200, user=pm)                                    # naive stale math would allow it
    assert e.value.status_code == 400 and "only 100 mm" in e.value.detail
    assert "stock unit" in e.value.detail                                   # the UNIT's fresh balance decided it


def test_two_connections_cannot_cut_more_than_is_issued(shared):
    s1, s2 = shared
    mat = _material(s1)
    make_wo(s1, "WO-1001")
    (unit,) = accepted_units(s1, mat, [1000])
    rid = new_routing(s1, mat)
    alloc = allocate(s1, rid, unit, 1000)
    reserve(s1, rid, alloc, 1000)
    issue(s1, rid, alloc, 1000)
    aid, uid = alloc.id, unit.id
    pm1 = _user(s1, UserRole.PRODUCTION_MANAGER)
    pm2 = s2.get(User, pm1.id)
    stale, stale_alloc = s2.get(Unit, uid), s2.get(Alloc, aid)               # B caches BOTH rows
    assert (stale.issued_length_mm, stale_alloc.issued_length_mm) == (1000, 1000)
    Rsv.cut_consume(s1, CCCutConsumeCreate(routing_id=rid, allocation_id=aid, stock_unit_id=uid, length_mm=700), pm1)
    assert (stale.issued_length_mm, stale_alloc.issued_length_mm) == (1000, 1000)    # B's copies are now stale
    with pytest.raises(HTTPException) as e:
        Rsv.cut_consume(s2, CCCutConsumeCreate(routing_id=rid, allocation_id=aid, stock_unit_id=uid, length_mm=400), pm2)
    assert e.value.status_code == 400 and "only 300 mm" in e.value.detail
    Rsv.cut_consume(s2, CCCutConsumeCreate(routing_id=rid, allocation_id=aid, stock_unit_id=uid, length_mm=300), pm2)
    s1.expire_all()
    final = s1.get(Unit, uid)
    assert (final.issued_length_mm, final.consumed_length_mm, final.remaining_length_mm) == (0, 1000, 0)
    assert final.status == "CONSUMED"
    assert_reconciled(s1, final)


# ------------------------------------------------------------------ atomicity
@pytest.mark.parametrize("model,event_name", [(Ledger, "before_insert"), (Unit, "after_update"),
                                              (Alloc, "after_update")])
def test_rollback_after_a_mid_transaction_failure(issued1000, model, event_name):
    """Ledger insert failure, unit update failure, allocation update failure: nothing partial remains."""
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    before = snapshot(db)
    off = _raising_listener(model, event_name)
    try:
        with pytest.raises(RuntimeError):
            cut(db, rid, alloc, 250)
    finally:
        off()
    assert snapshot(db) == before
    assert_reconciled(db, unit)
    assert cut(db, rid, alloc, 250).reconciled is True


def test_rollback_after_everything_was_flushed(issued1000, monkeypatch):
    db, alloc, rid = issued1000["db"], issued1000["alloc"], issued1000["rid"]
    before = snapshot(db)
    seen = {}

    def late(*a, **k):
        seen["rows"] = count(db, "cc_stock_ledger")
        raise RuntimeError("late failure")

    monkeypatch.setattr(rv_svc, "CCStockMovementResult", late)
    with pytest.raises(RuntimeError):
        cut(db, rid, alloc, 100)
    assert seen["rows"] == len(before["cc_stock_ledger"]) + 1
    assert snapshot(db) == before


# ------------------------------------------------------------------ numbering
def test_ledger_number_collision_is_retried_and_recovers(issued1000, monkeypatch):
    db, unit, alloc, rid = issued1000["db"], issued1000["unit"], issued1000["alloc"], issued1000["rid"]
    calls = _flaky(monkeypatch, ["TXN-000001"])                              # already taken by the INWARD row
    r = cut(db, rid, alloc, 100)
    assert len(calls) == 2 and r.ledger_transaction_number == "TXN-000004"
    assert db.query(Ledger).filter_by(movement_type="CUT_CONSUME").count() == 1
    assert_reconciled(db, unit)


def test_persistent_collision_is_a_controlled_409_with_nothing_changed(issued1000, monkeypatch):
    db, alloc, rid = issued1000["db"], issued1000["alloc"], issued1000["rid"]
    before = snapshot(db)
    calls = _flaky(monkeypatch, ["TXN-000001"] * 10)
    with pytest.raises(HTTPException) as e:
        cut(db, rid, alloc, 100)
    assert e.value.status_code == 409 and len(calls) == rv_svc.CC_NUMBER_MAX_ATTEMPTS
    assert snapshot(db) == before


# ------------------------------------------------------------------ OMS untouched
def test_existing_oms_rows_are_untouched_through_the_whole_flow(w1000):
    db, alloc, rid = w1000["db"], w1000["alloc"], w1000["rid"]
    before = oms_state(db)                                       # WO, WORoute, StageWIP, movements, entries ...
    reserve(db, rid, alloc, 1000)
    issue(db, rid, alloc, 700)
    cut(db, rid, alloc, 300)
    release(db, rid, alloc, 100)
    assert oms_state(db) == before
    for table in ("production_movements", "production_updates", "nc_records"):
        assert count(db, table) == 0
    assert count(db, "stage_wips") == 1 and count(db, "wo_routes") == 3 and count(db, "work_orders") == 1


# ------------------------------------------------------------------ randomized legitimate sequence
def test_random_legitimate_reserve_issue_cut_release_sequences_keep_every_invariant(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    rng = random.Random(20261004)
    accepted = {"reserve": 0, "issue": 0, "cut": 0, "release": 0}
    rejected = 0
    ops = {"reserve": reserve, "issue": issue, "cut": cut, "release": release}
    for _ in range(300):
        name, x = rng.choice(list(ops)), rng.randint(1, 350)
        try:
            ops[name](db, rid, alloc, x)
            accepted[name] += 1
        except HTTPException as e:
            assert e.status_code == 400
            rejected += 1
            continue
        a, u = fresh(db, Alloc, alloc.id), fresh(db, Unit, unit.id)
        assert a.reserved_length_mm + a.issued_length_mm + a.consumed_length_mm <= a.planned_length_mm
        assert u.reserved_length_mm + u.issued_length_mm <= u.remaining_length_mm
        assert u.remaining_length_mm + u.consumed_length_mm == u.original_length_mm
        assert min(u.reserved_length_mm, u.issued_length_mm, u.consumed_length_mm, a.reserved_length_mm,
                   a.issued_length_mm, a.consumed_length_mm) >= 0
        assert_reconciled(db, unit)
    assert all(n > 0 for n in accepted.values()), accepted                  # every operation really ran
    assert rejected > 20                                                    # and the limits really bit
    t = ledger_totals(db, unit.id)
    assert fresh(db, Unit, unit.id).consumed_length_mm == t.get("CUT_CONSUME", 0)
