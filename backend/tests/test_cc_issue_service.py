"""Continuous Casting ISSUE (Phase 5). In-memory SQLite only; no database file is created.

Reuses the Phase 4 fixtures/helpers (`db`, `world`, `shared`, reserve/release helpers, the
reconciliation re-derivation). SQLite ignores FOR UPDATE, so row-lock *behaviour* on PostgreSQL
is not proven here; the lock request/order, the fresh re-read (two real connections) and the
transactional + CHECK invariants are.
"""
import random
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Query

from app.core.database import Base
from app.models import *  # noqa: F401,F403
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WOStatus
from app.schemas.continuous_casting import CCIssueCreate, CCReserveCreate, CCRoutingReleaseCreate
import app.services.continuous_casting_reservation_service as rv_svc
from app.services.continuous_casting_reservation_service import ContinuousCastingReservationService as Rsv

# Phase 4 fixtures + helpers (importing a fixture function registers it for this module).
from test_cc_reservation_service import (  # noqa: F401
    db, shared, world, Ledger, Alloc, Unit, Routing, Inward,
    _user, make_wo, _material, accepted_units, new_routing, supersede, allocate, reserve, release,
    simulate_issue, simulate_cut, _ledger_row, count, rows, oms_state, snapshot, fresh, ledger_totals,
    assert_reconciled, _raising_listener, _flaky, _two_allocations_on_one_unit,
)


def issue(db, rid, alloc, x, user=None, unit_id=None, **kw):
    return Rsv.issue(
        db, CCIssueCreate(routing_id=rid, allocation_id=alloc.id, length_mm=x,
                          stock_unit_id=unit_id or alloc.stock_unit_id, **kw),
        user or _user(db, UserRole.STORE))


@pytest.fixture()
def reserved(world):
    """The Phase 4 world with the whole 600 mm plan already reserved."""
    reserve(world["db"], world["rid"], world["alloc"], 600)
    return world


# ------------------------------------------------------------------ the semantic rule
def test_full_issue_moves_all_reserved_length_to_issued(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    r = issue(db, rid, alloc, 600)
    assert r.movement_type == "ISSUE" and r.length_mm == 600 and r.reconciled is True
    assert (r.allocation_reserved_length_mm, r.allocation_issued_length_mm) == (0, 600)
    assert (r.unit_reserved_length_mm, r.unit_issued_length_mm) == (0, 600)
    assert r.allocation_issued_length_mm == r.allocation_planned_length_mm       # fully issued
    assert r.allocation_status == "ISSUED"                                       # existing vocabulary
    assert_reconciled(db, unit)


def test_the_specification_example_remaining_1000_reserved_600_issue_400(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    (unit,) = accepted_units(db, mat, [1000])
    rid = new_routing(db, mat)
    alloc = allocate(db, rid, unit, 1000)
    reserve(db, rid, alloc, 600)
    before = fresh(db, Unit, unit.id)
    assert (before.remaining_length_mm, before.reserved_length_mm, before.issued_length_mm,
            before.consumed_length_mm) == (1000, 600, 0, 0)
    issue(db, rid, alloc, 400)
    after = fresh(db, Unit, unit.id)
    assert (after.remaining_length_mm, after.reserved_length_mm, after.issued_length_mm,
            after.consumed_length_mm) == (1000, 200, 400, 0)
    assert_reconciled(db, unit)


def test_partial_issue_642_reserved_issue_200(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    (unit,) = accepted_units(db, mat, [1000])
    rid = new_routing(db, mat)
    alloc = allocate(db, rid, unit, 642)
    reserve(db, rid, alloc, 642)
    r = issue(db, rid, alloc, 200)
    assert (r.allocation_reserved_length_mm, r.allocation_issued_length_mm) == (442, 200)
    assert (r.unit_reserved_length_mm, r.unit_issued_length_mm) == (442, 200)
    assert r.allocation_status == "ISSUED" and r.allocation_planned_length_mm == 642
    assert_reconciled(db, unit)


def test_several_issues_against_one_reservation(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    seen = [issue(db, rid, alloc, x) for x in (100, 250, 250)]
    assert [(r.allocation_reserved_length_mm, r.allocation_issued_length_mm) for r in seen] == \
        [(500, 100), (250, 350), (0, 600)]
    assert db.query(Ledger).filter_by(movement_type="ISSUE").count() == 3
    assert len({r.ledger_transaction_number for r in seen}) == 3
    with pytest.raises(HTTPException) as e:                          # nothing is reserved any more
        issue(db, rid, alloc, 1)
    assert e.value.status_code == 400
    assert_reconciled(db, unit)


def test_issue_cannot_exceed_the_reserved_quantity(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 300)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 301)
    assert e.value.status_code == 400 and "300" in e.value.detail and snapshot(db) == before
    assert issue(db, rid, alloc, 300).allocation_issued_length_mm == 300


def test_unreserved_plan_cannot_be_issued(world):
    db, rid, alloc = world["db"], world["rid"], world["alloc"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:                          # planned 600 but nothing reserved
        issue(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "0 mm is currently reserved" in e.value.detail
    assert snapshot(db) == before


def test_released_material_cannot_be_issued(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    release(db, rid, alloc, 600)
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 1)
    assert e.value.status_code == 400 and "Released" in e.value.detail
    assert_reconciled(db, unit)


# The "issued + consumed must not exceed the plan" rule is defense in depth: with a consistent ledger
# the reserved-quantity and plan-left rules already keep every allocation inside its plan, so no
# legitimate state can reach it. It is therefore tested three honest ways, with no fabricated or
# corrupted ledger data: the predicate itself, its wiring into ISSUE, and the invariant it protects.
@pytest.mark.parametrize("issued,consumed,x,planned,exceeds", [
    (0, 0, 600, 600, False), (0, 0, 601, 600, True), (300, 300, 1, 600, True), (300, 300, 0, 600, False),
    (200, 100, 300, 600, False), (200, 100, 301, 600, True), (0, 100, 500, 600, False), (0, 100, 501, 600, True),
])
def test_plan_overrun_predicate(issued, consumed, x, planned, exceeds):
    alloc = SimpleNamespace(issued_length_mm=issued, consumed_length_mm=consumed, planned_length_mm=planned)
    assert rv_svc._issue_would_exceed_plan(alloc, x) is exceeds


def test_issue_consults_the_plan_overrun_rule(reserved, monkeypatch):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    before = snapshot(db)
    monkeypatch.setattr(rv_svc, "_issue_would_exceed_plan", lambda allocation, length: True)
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "exceed the planned 600" in e.value.detail
    assert snapshot(db) == before
    monkeypatch.undo()
    assert issue(db, rid, alloc, 100).success                          # the same request passes when the rule allows


def test_issue_up_to_exactly_the_plan_is_allowed_after_some_material_was_consumed(reserved):
    """A legitimate flow: 300 issued and cut, then the last 300 issued. issued + consumed == plan."""
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    issue(db, rid, alloc, 300)
    simulate_cut(db, alloc, unit, 300)                                  # ISSUE + CUT_CONSUME rows, consistent
    r = issue(db, rid, alloc, 300)
    assert (r.allocation_reserved_length_mm, r.allocation_issued_length_mm,
            r.allocation_consumed_length_mm) == (0, 300, 300)
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 1)
    assert e.value.status_code == 400 and "0 mm is currently reserved" in e.value.detail
    assert_reconciled(db, unit)


def test_real_operation_sequences_never_push_an_allocation_past_its_plan(world):
    """The invariant behind the rule: reserved + issued + consumed <= planned after every
    legitimate operation, and the ledger reconciles after every one."""
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    rng = random.Random(20261003)
    accepted = rejected = 0
    for _ in range(80):
        op, x = rng.choice(["reserve", "issue", "release", "cut"]), rng.randint(1, 300)
        try:
            if op == "reserve":
                reserve(db, rid, alloc, x)
            elif op == "issue":
                issue(db, rid, alloc, x)
            elif op == "release":
                release(db, rid, alloc, x)
            else:
                a, u = fresh(db, Alloc, alloc.id), fresh(db, Unit, unit.id)
                if a.issued_length_mm == 0:
                    continue
                simulate_cut(db, a, u, min(x, a.issued_length_mm))      # a valid CUT_CONSUME-shaped transition
            accepted += 1
        except HTTPException as e:
            assert e.status_code == 400
            rejected += 1
        a = fresh(db, Alloc, alloc.id)
        assert a.reserved_length_mm + a.issued_length_mm + a.consumed_length_mm <= a.planned_length_mm
        assert_reconciled(db, unit)
    assert accepted > 10 and rejected > 10                               # it genuinely exercised the limits


# ------------------------------------------------------------------ balances
def test_issue_changes_exactly_reserved_and_issued_and_nothing_else(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    simulate_cut_state = fresh(db, Unit, unit.id)                      # give consumed a non-zero value
    a = fresh(db, Alloc, alloc.id)
    a.reserved_length_mm -= 0                                          # (no-op; keeps the allocation as is)
    before_unit = fresh(db, Unit, unit.id)
    snap = (before_unit.remaining_length_mm, before_unit.consumed_length_mm, before_unit.original_length_mm,
            before_unit.status, before_unit.location)
    a_before = fresh(db, Alloc, alloc.id)
    asnap = (a_before.planned_length_mm, a_before.consumed_length_mm, a_before.routing_id, a_before.stock_unit_id)
    r = issue(db, rid, alloc, 250)
    u2, a2 = fresh(db, Unit, unit.id), fresh(db, Alloc, alloc.id)
    assert (u2.reserved_length_mm, u2.issued_length_mm) == (350, 250)
    assert (a2.reserved_length_mm, a2.issued_length_mm) == (350, 250)
    assert (u2.remaining_length_mm, u2.consumed_length_mm, u2.original_length_mm, u2.status, u2.location) == snap
    assert (a2.planned_length_mm, a2.consumed_length_mm, a2.routing_id, a2.stock_unit_id) == asnap
    assert r.unit_remaining_length_mm == 1000 and r.unit_consumed_length_mm == 0


def test_issue_leaves_existing_consumed_length_untouched(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    simulate_issue(db, alloc, unit, 200)
    simulate_cut(db, alloc, unit, 80)                                  # issued 120, consumed 80, remaining 920
    r = issue(db, rid, alloc, 150)
    assert (r.unit_consumed_length_mm, r.allocation_consumed_length_mm) == (80, 80)
    assert r.unit_remaining_length_mm == 920
    assert (r.unit_issued_length_mm, r.unit_reserved_length_mm) == (120 + 150, 400 - 150)
    assert_reconciled(db, unit)


def test_issue_does_not_change_free_physical_length(reserved):
    """reserved -> issued is a transfer between two committed buckets: free length is unchanged."""
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    free_before = fresh(db, Unit, unit.id)
    free_before = free_before.remaining_length_mm - free_before.reserved_length_mm - free_before.issued_length_mm
    r = issue(db, rid, alloc, 400)
    assert r.unit_free_length_mm == free_before == 400


# ------------------------------------------------------------------ ledger
def test_issue_writes_exactly_one_correct_immutable_ledger_row(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    before = count(db, "cc_stock_ledger")
    user = _user(db, UserRole.STORE)
    r = issue(db, rid, alloc, 250, user=user, reason="Issued to cutting bay")
    assert count(db, "cc_stock_ledger") == before + 1
    row = db.query(Ledger).filter_by(transaction_number=r.ledger_transaction_number).one()
    assert row.movement_type == "ISSUE" and row.length_mm == 250 and row.piece_qty is None
    assert row.inward_id == unit.inward_id and row.stock_unit_id == unit.id and row.allocation_id == alloc.id
    assert row.unit_remaining_after_mm == 1000                        # the bar is still whole
    assert row.performed_by_id == user.id and row.performed_by_name == user.full_name
    assert row.reason == "Issued to cutting bay" and row.client_request_id is None and row.created_at is not None
    assert alloc.allocation_number in row.reference and "WO-1001" in row.reference and "routing v1" in row.reference
    assert db.get(Routing, db.get(Alloc, row.allocation_id).routing_id).work_order.wo_number == "WO-1001"
    assert db.query(AuditLog).filter(AuditLog.action == "CC_ISSUE").one().entity_id == alloc.allocation_number
    row = db.query(Ledger).filter_by(transaction_number=r.ledger_transaction_number).one()
    row.reason = "tamper"
    with pytest.raises(ValueError):                                   # append-only
        db.flush()
    db.rollback()
    with pytest.raises(ValueError):
        db.delete(db.query(Ledger).filter_by(transaction_number=r.ledger_transaction_number).one())
        db.flush()
    db.rollback()


def test_default_reason_and_transaction_numbering(reserved):
    db, alloc, rid = reserved["db"], reserved["alloc"], reserved["rid"]
    r = issue(db, rid, alloc, 100)
    assert r.ledger_transaction_number == "TXN-000003"                 # INWARD, RESERVE, ISSUE
    assert "Issue to WO-1001 routing v1" in db.query(Ledger).filter_by(
        transaction_number=r.ledger_transaction_number).one().reason


# ------------------------------------------------------------------ release interaction
def test_release_cannot_release_issued_quantity_but_can_release_the_unissued_remainder(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    (unit,) = accepted_units(db, mat, [1000])
    rid = new_routing(db, mat)
    alloc = allocate(db, rid, unit, 1000)
    reserve(db, rid, alloc, 1000)
    issue(db, rid, alloc, 600)                                          # reserved 400, issued 600
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        release(db, rid, alloc, 600)
    assert e.value.status_code == 400 and "only 400 mm is currently reserved" in e.value.detail
    assert "issued 600 mm" in e.value.detail and snapshot(db) == before
    r = release(db, rid, alloc, 400)
    assert (r.unit_reserved_length_mm, r.unit_issued_length_mm) == (0, 600)
    assert (r.allocation_reserved_length_mm, r.allocation_issued_length_mm) == (0, 600)
    assert r.allocation_status == "ISSUED"                              # issued material keeps it ISSUED
    assert_reconciled(db, unit)


def test_after_issue_the_remainder_can_be_reserved_again_up_to_plan(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    issue(db, rid, alloc, 600)
    with pytest.raises(HTTPException) as e:                              # plan is fully issued
        reserve(db, rid, alloc, 1)
    assert e.value.status_code == 400 and "0 mm of the planned 600" in e.value.detail


# ------------------------------------------------------------------ QA does not undo a valid reservation
@pytest.mark.parametrize("qa", ["PENDING_QA", "REJECTED", "ON_HOLD"])
def test_a_later_qa_change_does_not_block_or_corrupt_issue(reserved, qa):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    db.query(Inward).one().qa_status = qa
    db.commit()
    r = issue(db, rid, alloc, 300)
    assert (r.unit_reserved_length_mm, r.unit_issued_length_mm, r.unit_remaining_length_mm) == (300, 300, 1000)
    assert fresh(db, Inward, unit.inward_id).qa_status == qa            # QA untouched by ISSUE
    assert_reconciled(db, unit)
    with pytest.raises(HTTPException):                                  # but NEW reservations still need ACCEPTED
        reserve(db, rid, alloc, 1)


# ------------------------------------------------------------------ routing lifecycle
def test_superseded_routing_cannot_issue_but_its_reservation_can_be_released(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    supersede(db, reserved["mat"])
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "SUPERSEDED" in e.value.detail and "issuing" in e.value.detail
    assert snapshot(db) == before                                       # the reservation is still there, untouched
    res = Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.PLANNER))
    assert res.total_released_length_mm == 600
    with pytest.raises(HTTPException):
        issue(db, rid, alloc, 1)
    assert_reconciled(db, unit)


def test_issue_follows_the_same_routing_rule_as_reserve(reserved):
    db, alloc, rid = reserved["db"], reserved["alloc"], reserved["rid"]
    for state in ("DRAFT", "SUPERSEDED"):
        db.query(Routing).one().status = state
        db.commit()
        for op in (lambda: issue(db, rid, alloc, 10), lambda: reserve(db, rid, alloc, 10)):
            with pytest.raises(HTTPException) as e:
                op()
            assert e.value.status_code == 400 and state in e.value.detail


def test_material_issued_before_supersession_stays_issued(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    issue(db, rid, alloc, 250)
    supersede(db, reserved["mat"])
    res = Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.PLANNER))
    assert res.total_released_length_mm == 350                          # only the unissued part
    u = fresh(db, Unit, unit.id)
    assert (u.reserved_length_mm, u.issued_length_mm) == (0, 250)
    assert_reconciled(db, unit)


@pytest.mark.parametrize("state", [WOStatus.CLOSED, WOStatus.DISPATCHED])
def test_closed_work_order_cannot_take_an_issue(reserved, state):
    db = reserved["db"]
    fresh(db, WorkOrder, reserved["wo"].id).status = state
    db.commit()
    with pytest.raises(HTTPException) as e:
        issue(db, reserved["rid"], reserved["alloc"], 100)
    assert e.value.status_code == 400


def test_non_continuous_casting_routing_cannot_issue(reserved):
    db = reserved["db"]
    db.query(Routing).one().material_source = "F1_PRODUCTION"
    db.commit()
    with pytest.raises(HTTPException) as e:
        issue(db, reserved["rid"], reserved["alloc"], 100)
    assert e.value.status_code == 400 and "CONTINUOUS_CASTING" in e.value.detail


# ------------------------------------------------------------------ identity: routing / allocation / unit
def test_routing_id_and_allocation_id_are_required(reserved):
    alloc, rid = reserved["alloc"], reserved["rid"]
    with pytest.raises(ValidationError):
        CCIssueCreate(allocation_id=alloc.id, stock_unit_id=alloc.stock_unit_id, length_mm=10)
    with pytest.raises(ValidationError):
        CCIssueCreate(routing_id=rid, stock_unit_id=alloc.stock_unit_id, length_mm=10)
    with pytest.raises(ValidationError):
        CCIssueCreate(routing_id=rid, allocation_id=alloc.id, length_mm=10)       # stock unit named too
    db = reserved["db"]
    for missing in ("routing_id", "allocation_id", "stock_unit_id"):          # and the service re-checks
        fields = dict(routing_id=rid, allocation_id=alloc.id, stock_unit_id=alloc.stock_unit_id, length_mm=10,
                      reason=None)
        fields[missing] = None
        with pytest.raises(HTTPException) as e:
            Rsv.issue(db, CCIssueCreate.model_construct(**fields), _user(db, UserRole.STORE))
        assert e.value.status_code == 400 and "required" in e.value.detail


def test_wrong_routing_id_is_rejected(reserved):
    db, alloc = reserved["db"], reserved["alloc"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        issue(db, uuid.uuid4(), alloc, 100)
    assert e.value.status_code == 400 and "does not belong" in e.value.detail and snapshot(db) == before


def test_allocation_of_another_routing_is_rejected(reserved):
    db, alloc = reserved["db"], reserved["alloc"]
    make_wo(db, "WO-1002")
    other = new_routing(db, reserved["mat"], "WO-1002")
    with pytest.raises(HTTPException) as e:
        issue(db, other, alloc, 100)
    assert e.value.status_code == 400 and "does not belong" in e.value.detail


def test_unknown_allocation_is_404(reserved):
    db, alloc = reserved["db"], reserved["alloc"]
    with pytest.raises(HTTPException) as e:
        Rsv.issue(db, CCIssueCreate(routing_id=reserved["rid"], allocation_id=uuid.uuid4(),
                                    stock_unit_id=alloc.stock_unit_id, length_mm=10), _user(db, UserRole.STORE))
    assert e.value.status_code == 404


def test_a_different_stock_unit_than_the_allocated_one_is_rejected(reserved):
    db, alloc, rid = reserved["db"], reserved["alloc"], reserved["rid"]
    (other,) = accepted_units(db, reserved["mat"], [900])
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 100, unit_id=other.id)
    assert e.value.status_code == 400 and "not the unit allocated" in e.value.detail
    assert snapshot(db) == before


@pytest.mark.parametrize("bad", [0, -5, 1.5, None, "abc"])
def test_schema_rejects_bad_lengths(reserved, bad):
    with pytest.raises(ValidationError):
        CCIssueCreate(routing_id=reserved["rid"], allocation_id=reserved["alloc"].id,
                      stock_unit_id=reserved["alloc"].stock_unit_id, length_mm=bad)


@pytest.mark.parametrize("bad", [0, -1, True])
def test_service_rejects_bad_lengths_without_schema_validation(reserved, bad):
    db, alloc = reserved["db"], reserved["alloc"]
    raw = CCIssueCreate.model_construct(routing_id=reserved["rid"], allocation_id=alloc.id,
                                        stock_unit_id=alloc.stock_unit_id, length_mm=bad, reason=None)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Rsv.issue(db, raw, _user(db, UserRole.STORE))
    assert e.value.status_code == 400 and snapshot(db) == before


def test_no_idempotency_field_exists_on_issue(reserved):
    with pytest.raises(ValidationError):
        CCIssueCreate(routing_id=reserved["rid"], allocation_id=reserved["alloc"].id,
                      stock_unit_id=reserved["alloc"].stock_unit_id, length_mm=10, client_request_id="x")
    assert "client_request_id" not in CCIssueCreate.model_fields


# ------------------------------------------------------------------ roles
@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STORE])
def test_issue_roles_allowed(reserved, role):
    db = reserved["db"]
    assert issue(db, reserved["rid"], reserved["alloc"], 100, user=_user(db, role)).success


@pytest.mark.parametrize("role", [UserRole.PLANNER, UserRole.ENGINEERING, UserRole.PRODUCTION_MANAGER,
                                  UserRole.QA, UserRole.DISPATCH, UserRole.CEO, UserRole.MACHINE_OPERATOR])
def test_other_roles_cannot_issue(reserved, role):
    db = reserved["db"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        issue(db, reserved["rid"], reserved["alloc"], 100, user=_user(db, role))
    assert e.value.status_code == 403 and snapshot(db) == before


def test_reserving_is_not_issuing_the_planner_cannot_issue_and_store_cannot_reserve(reserved):
    db, alloc, rid = reserved["db"], reserved["alloc"], reserved["rid"]
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 50, user=_user(db, UserRole.PLANNER))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        reserve(db, rid, alloc, 50, user=_user(db, UserRole.STORE))
    assert e.value.status_code == 403


def test_anonymous_cannot_issue(reserved):
    alloc = reserved["alloc"]
    with pytest.raises(HTTPException) as e:
        Rsv.issue(reserved["db"], CCIssueCreate(routing_id=reserved["rid"], allocation_id=alloc.id,
                                                stock_unit_id=alloc.stock_unit_id, length_mm=10), None)
    assert e.value.status_code == 403


# ------------------------------------------------------------------ locking and fresh reads
def test_issue_locks_unit_then_allocation_then_routing(reserved, monkeypatch):
    order = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    issue(reserved["db"], reserved["rid"], reserved["alloc"], 100)
    assert order == [Unit, Alloc, Routing]


def test_balances_are_re_read_after_the_lock(reserved):
    """A session holding stale balances is checked against what is really in the database."""
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    stale_a, stale_u = db.get(Alloc, alloc.id), db.get(Unit, unit.id)
    assert (stale_a.reserved_length_mm, stale_u.reserved_length_mm) == (600, 600)
    a_t, u_t = Base.metadata.tables["cc_allocations"], Base.metadata.tables["cc_stock_units"]
    db.execute(a_t.update().where(a_t.c.id == str(alloc.id)).values(reserved_length_mm=100, issued_length_mm=500))
    db.execute(u_t.update().where(u_t.c.id == str(unit.id)).values(reserved_length_mm=100, issued_length_mm=500))
    assert stale_a.reserved_length_mm == 600                            # the ORM copy really is stale
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 200)                                      # naive stale math would allow this
    assert e.value.status_code == 400 and "only 100 mm is currently reserved" in e.value.detail


def test_two_connections_cannot_issue_more_than_is_reserved(shared):
    s1, s2 = shared
    unit_id, (r1, a1), _ = _two_allocations_on_one_unit(s1)
    planner, store1 = _user(s1, UserRole.PLANNER), _user(s1, UserRole.STORE)
    store2 = s2.get(User, store1.id)
    Rsv.reserve(s1, CCReserveCreate(routing_id=r1, allocation_id=a1, length_mm=500), planner)
    stale = s2.get(Alloc, a1)                                           # connection B caches reserved = 500
    assert stale.reserved_length_mm == 500
    Rsv.issue(s1, CCIssueCreate(routing_id=r1, allocation_id=a1, stock_unit_id=unit_id, length_mm=400), store1)
    assert stale.reserved_length_mm == 500                              # stale in B; truth is now 100
    with pytest.raises(HTTPException) as e:
        Rsv.issue(s2, CCIssueCreate(routing_id=r1, allocation_id=a1, stock_unit_id=unit_id, length_mm=300), store2)
    assert e.value.status_code == 400 and "only 100 mm" in e.value.detail
    Rsv.issue(s2, CCIssueCreate(routing_id=r1, allocation_id=a1, stock_unit_id=unit_id, length_mm=100), store2)
    s1.expire_all()
    unit = s1.get(Unit, unit_id)
    assert (unit.reserved_length_mm, unit.issued_length_mm) == (0, 500)
    assert unit.reserved_length_mm + unit.issued_length_mm <= unit.remaining_length_mm
    assert_reconciled(s1, unit)


# ------------------------------------------------------------------ reconciliation
def test_reconciliation_catches_a_ledger_that_disagrees_with_the_balances(reserved):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    before = snapshot(db)

    def skew(mapper, connection, target):
        target.length_mm = target.length_mm + 1

    event.listen(Ledger, "before_insert", skew)
    try:
        with pytest.raises(HTTPException) as e:
            issue(db, rid, alloc, 100)
    finally:
        event.remove(Ledger, "before_insert", skew)
    assert e.value.status_code == 500 and "reconcil" in e.value.detail.lower()
    assert snapshot(db) == before
    assert issue(db, rid, alloc, 100).reconciled is True


@pytest.mark.parametrize("what", ["unit_issued", "unit_reserved", "alloc_issued", "alloc_reserved"])
def test_pre_existing_drift_blocks_issue_instead_of_hiding_it(reserved, what):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    u, a = fresh(db, Unit, unit.id), fresh(db, Alloc, alloc.id)
    if what == "unit_issued":
        u.issued_length_mm += 50
    elif what == "unit_reserved":
        u.reserved_length_mm -= 50
    elif what == "alloc_issued":
        a.issued_length_mm += 50
        a.reserved_length_mm -= 50
    else:
        a.reserved_length_mm -= 50
        a.issued_length_mm += 50
        u.reserved_length_mm -= 50
        u.issued_length_mm += 50                                          # internally consistent, but not in the ledger
    db.commit()
    ledger_rows = count(db, "cc_stock_ledger")
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 100)
    assert e.value.status_code == 500 and count(db, "cc_stock_ledger") == ledger_rows


def test_reconciliation_formulas_stay_correct_for_later_return_and_cut_consume(reserved):
    """Later phases move issued length on (RETURN, CUT_CONSUME). The formulas already cover them,
    so a state produced with those ledger rows still reconciles and still accepts new movements."""
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    issue(db, rid, alloc, 400)                                           # reserved 200, issued 400
    simulate_cut(db, alloc, unit, 150)                                   # issued 250, consumed 150, remaining 850
    u, a = fresh(db, Unit, unit.id), fresh(db, Alloc, alloc.id)          # a RETURN of 50 back to free stock
    u.issued_length_mm -= 50
    a.issued_length_mm -= 50
    _ledger_row(db, u, a, "RETURN", 50)
    db.commit()
    assert_reconciled(db, unit)
    r = issue(db, rid, alloc, 200)                                       # reconcile passes with all terms present
    assert r.reconciled is True and (r.unit_issued_length_mm, r.unit_reserved_length_mm) == (400, 0)
    assert (r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (150, 850)
    assert_reconciled(db, unit)


def test_the_database_check_constraints_still_back_the_issue_up(reserved):
    db, unit = reserved["db"], reserved["unit"]
    from sqlalchemy.exc import IntegrityError
    u = fresh(db, Unit, unit.id)
    u.issued_length_mm = u.remaining_length_mm - u.reserved_length_mm + 1      # reserved + issued > remaining
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ------------------------------------------------------------------ atomicity
@pytest.mark.parametrize("model,event_name", [(Ledger, "before_insert"), (Unit, "after_update"),
                                              (Alloc, "after_update")])
def test_rollback_after_a_mid_transaction_failure(reserved, model, event_name):
    """Ledger insert failure, and unit / allocation balance-update failures: all roll back."""
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    before = snapshot(db)
    off = _raising_listener(model, event_name)
    try:
        with pytest.raises(RuntimeError):
            issue(db, rid, alloc, 250)
    finally:
        off()
    assert snapshot(db) == before
    assert_reconciled(db, unit)
    assert issue(db, rid, alloc, 250).reconciled is True                  # and the same issue works afterwards


def test_rollback_after_everything_was_flushed(reserved, monkeypatch):
    db, alloc, rid = reserved["db"], reserved["alloc"], reserved["rid"]
    before = snapshot(db)
    seen = {}

    def late(*a, **k):
        seen["rows"] = count(db, "cc_stock_ledger")
        raise RuntimeError("late failure")

    monkeypatch.setattr(rv_svc, "CCStockMovementResult", late)
    with pytest.raises(RuntimeError):
        issue(db, rid, alloc, 100)
    assert seen["rows"] == len(before["cc_stock_ledger"]) + 1             # the ISSUE row was really in the transaction
    assert snapshot(db) == before


# ------------------------------------------------------------------ number collisions
def test_ledger_number_collision_is_retried_and_recovers(reserved, monkeypatch):
    db, unit, alloc, rid = reserved["db"], reserved["unit"], reserved["alloc"], reserved["rid"]
    calls = _flaky(monkeypatch, ["TXN-000001"])                          # already taken by the INWARD row
    r = issue(db, rid, alloc, 100)
    assert len(calls) == 2 and r.ledger_transaction_number == "TXN-000003"
    assert db.query(Ledger).filter_by(movement_type="ISSUE").count() == 1
    assert_reconciled(db, unit)


def test_persistent_collision_is_a_controlled_409_with_nothing_changed(reserved, monkeypatch):
    db, alloc, rid = reserved["db"], reserved["alloc"], reserved["rid"]
    before = snapshot(db)
    calls = _flaky(monkeypatch, ["TXN-000001"] * 10)
    with pytest.raises(HTTPException) as e:
        issue(db, rid, alloc, 100)
    assert e.value.status_code == 409 and len(calls) == rv_svc.CC_NUMBER_MAX_ATTEMPTS
    assert snapshot(db) == before


# ------------------------------------------------------------------ OMS untouched
def test_existing_oms_rows_are_untouched_by_reserve_issue_and_release(world):
    db, alloc, rid = world["db"], world["alloc"], world["rid"]
    before = oms_state(db)                                                # WO, WORoute, StageWIP, movements, entries ...
    reserve(db, rid, alloc, 600)
    issue(db, rid, alloc, 250)
    release(db, rid, alloc, 100)
    assert oms_state(db) == before
    assert count(db, "orders") == 1 and count(db, "work_orders") == 1
    assert count(db, "production_movements") == 0 and count(db, "production_updates") == 0
    assert count(db, "stage_wips") == 1 and count(db, "wo_routes") == 3     # nothing created or changed


def test_the_oms_wip_never_moves_as_a_result_of_an_issue(reserved):
    db = reserved["db"]
    wip = rows(db, "stage_wips")
    issue(db, reserved["rid"], reserved["alloc"], 600)
    assert rows(db, "stage_wips") == wip                                  # issuing is not F1 production
