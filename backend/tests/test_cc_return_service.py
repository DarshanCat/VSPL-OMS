"""Continuous Casting RETURN (Phase 7). In-memory SQLite only; no database file is created.

RETURN hands ISSUED, not-yet-cut stock back: issued - X on the unit and the allocation, and
NOTHING else. `remaining` is untouched (ISSUE never removed it -- the bar was always whole) and so
are reserved and consumed. The returned length is "free" again because
free = remaining - reserved - issued.

SQLite ignores FOR UPDATE, so PostgreSQL row-lock behaviour is not proven here; the lock
request/order, the post-lock re-read (two real connections), rollback and the invariants are.
"""
import random
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query
from sqlalchemy import event

from app.core.database import Base
from app.models import *  # noqa: F401,F403
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WOStatus
from app.schemas.continuous_casting import CCReturnCreate
import app.services.continuous_casting_reservation_service as rv_svc
from app.services.continuous_casting_reservation_service import ContinuousCastingReservationService as Rsv

from test_cc_reservation_service import (  # noqa: F401
    db, shared, world, Ledger, Alloc, Unit, Routing, Inward,
    _user, make_wo, _material, accepted_units, new_routing, supersede, allocate, reserve, release,
    _ledger_row, count, rows, oms_state, snapshot, fresh, ledger_totals, assert_reconciled,
    _raising_listener, _flaky,
)
from test_cc_issue_service import issue  # noqa: F401
from test_cc_cut_consume_service import w1000, mixed, cut  # noqa: F401


def ret(db, rid, alloc, x, user=None, unit_id=None, inward_id=None, **kw):
    uid = unit_id or alloc.stock_unit_id
    iid = inward_id or db.get(Unit, alloc.stock_unit_id).inward_id
    return Rsv.return_stock(
        db, CCReturnCreate(routing_id=rid, allocation_id=alloc.id, stock_unit_id=uid, inward_id=iid,
                           length_mm=x, **kw),
        user or _user(db, UserRole.STORE))


def free(db, unit_id):
    u = fresh(db, Unit, unit_id)
    return u.remaining_length_mm - u.reserved_length_mm - u.issued_length_mm


def bal(db, unit_id, alloc_id):
    u, a = fresh(db, Unit, unit_id), fresh(db, Alloc, alloc_id)
    return ((u.remaining_length_mm, u.reserved_length_mm, u.issued_length_mm, u.consumed_length_mm),
            (a.reserved_length_mm, a.issued_length_mm, a.consumed_length_mm))


@pytest.fixture()
def issued600(w1000):
    """1000 mm unit, plan 1000; 600 mm reserved and then issued: reserved 0, issued 600, remaining 1000."""
    reserve(w1000["db"], w1000["rid"], w1000["alloc"], 600)
    issue(w1000["db"], w1000["rid"], w1000["alloc"], 600)
    return w1000


# ------------------------------------------------------------------ the semantic rule
def test_partial_return_frees_length_and_changes_only_issued(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    assert free(db, unit.id) == 400                                       # 1000 - 0 - 600
    r = ret(db, rid, alloc, 200)
    assert r.movement_type == "RETURN" and r.length_mm == 200 and r.reconciled is True
    assert (r.unit_issued_length_mm, r.unit_remaining_length_mm) == (400, 1000)    # remaining NOT changed
    assert (r.unit_reserved_length_mm, r.unit_consumed_length_mm) == (0, 0)
    assert (r.allocation_issued_length_mm, r.allocation_reserved_length_mm, r.allocation_consumed_length_mm) == (400, 0, 0)
    assert r.unit_free_length_mm == 600 == free(db, unit.id)                # 400 -> 600 free
    assert r.allocation_status == "ISSUED" and "free stock again" in r.message
    assert_reconciled(db, unit)


def test_full_return_restores_the_available_length(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    ret(db, rid, alloc, 200)
    r = ret(db, rid, alloc, 400)                                          # the remaining issued 400
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (0, 0, 1000)
    assert free(db, unit.id) == 1000                                      # everything is free stock again
    assert r.allocation_status == "PLANNED"                               # active routing: the plan stands
    assert_reconciled(db, unit)


def test_a_single_full_return(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    r = ret(db, rid, alloc, 600)
    assert (r.unit_issued_length_mm, r.unit_remaining_length_mm, r.unit_free_length_mm) == (0, 1000, 1000)
    assert r.allocation_issued_length_mm == 0
    assert_reconciled(db, unit)


def test_return_after_a_partial_cut_never_touches_consumed(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    cut(db, rid, alloc, 200)                                              # issued 400, consumed 200, remaining 800
    r = ret(db, rid, alloc, 400)
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (0, 200, 800)
    assert (r.unit_reserved_length_mm, r.allocation_reserved_length_mm) == (0, 0)
    assert (r.allocation_issued_length_mm, r.allocation_consumed_length_mm) == (0, 200)
    assert r.allocation_status == "PARTIALLY_CONSUMED"                    # consumed history keeps its status
    assert free(db, unit.id) == 800
    assert_reconciled(db, unit)


def test_only_the_issued_part_is_returnable_when_part_is_consumed(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    (unit,) = accepted_units(db, mat, [1000])
    rid = new_routing(db, mat)
    alloc = allocate(db, rid, unit, 1000)
    reserve(db, rid, alloc, 1000), issue(db, rid, alloc, 1000)
    cut(db, rid, alloc, 400)                                              # issued 600, consumed 400, remaining 600
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 601)                                          # issued + consumed (1000) is NOT the limit
    assert e.value.status_code == 400 and "only 600 mm is currently issued" in e.value.detail
    r = ret(db, rid, alloc, 600)
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (0, 400, 600)
    assert_reconciled(db, unit)


# ------------------------------------------------------------------ amounts
def test_return_cannot_exceed_issued(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 601)
    assert e.value.status_code == 400 and "600" in e.value.detail and snapshot(db) == before
    ret(db, rid, alloc, 200)
    with pytest.raises(HTTPException):
        ret(db, rid, alloc, 401)                                          # cumulative, not per call
    ret(db, rid, alloc, 400)


def test_returned_or_free_material_cannot_be_returned_again(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    ret(db, rid, alloc, 600)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:                               # 1000 mm is free, but none is issued
        ret(db, rid, alloc, 1)
    assert e.value.status_code == 400 and "0 mm is currently issued" in e.value.detail
    assert snapshot(db) == before


@pytest.mark.parametrize("bad", [0, -5, 1.5, None, "abc"])
def test_schema_rejects_zero_negative_and_non_integer_returns(issued600, bad):
    alloc = issued600["alloc"]
    with pytest.raises(ValidationError):
        CCReturnCreate(routing_id=issued600["rid"], allocation_id=alloc.id, stock_unit_id=alloc.stock_unit_id,
                       inward_id=issued600["unit"].inward_id, length_mm=bad)


@pytest.mark.parametrize("bad", [0, -1, True])
def test_service_rejects_bad_lengths_without_schema_validation(issued600, bad):
    db, alloc = issued600["db"], issued600["alloc"]
    raw = CCReturnCreate.model_construct(routing_id=issued600["rid"], allocation_id=alloc.id,
                                         stock_unit_id=alloc.stock_unit_id, inward_id=issued600["unit"].inward_id,
                                         length_mm=bad, reason=None)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Rsv.return_stock(db, raw, _user(db, UserRole.STORE))
    assert e.value.status_code == 400 and snapshot(db) == before


def test_reserved_only_material_cannot_be_returned(w1000):
    db, alloc, rid = w1000["db"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 600)                                          # reserved, never issued
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "Reserved material is released, not returned" in e.value.detail
    assert snapshot(db) == before
    assert release(db, rid, alloc, 600).unit_reserved_length_mm == 0        # releasing is the right tool


def test_fully_consumed_material_cannot_be_returned(w1000):
    db, alloc, rid = w1000["db"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 1000), issue(db, rid, alloc, 1000)
    cut(db, rid, alloc, 1000)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 1)
    assert e.value.status_code == 400 and "consumed material (1000 mm) is gone" in e.value.detail
    assert snapshot(db) == before


# ------------------------------------------------------------------ routing lifecycle
def test_active_routing_can_return(issued600):
    db = issued600["db"]
    assert ret(db, issued600["rid"], issued600["alloc"], 100).success


def test_superseded_routing_can_return(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    supersede(db, issued600["mat"])
    r = ret(db, rid, alloc, 600)
    assert r.success and (r.unit_issued_length_mm, r.unit_remaining_length_mm) == (0, 1000)
    assert r.allocation_status == "RELEASED"                               # superseded + nothing held: historical close
    assert free(db, unit.id) == 1000
    assert_reconciled(db, unit)


def test_reserve_issue_supersede_return_succeeds_and_cut_stays_rejected(issued600):
    """The Phase 6 stranded-stock case: RETURN resolves it; CUT_CONSUME is deliberately NOT weakened."""
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    supersede(db, issued600["mat"])
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        cut(db, rid, alloc, 100)                                           # still refused on a superseded routing
    assert e.value.status_code == 400 and "SUPERSEDED" in e.value.detail and snapshot(db) == before
    assert ret(db, rid, alloc, 600).unit_issued_length_mm == 0             # ... but the stock can come home
    with pytest.raises(HTTPException):
        cut(db, rid, alloc, 100)
    assert_reconciled(db, unit)


def test_a_superseded_routing_returns_only_the_uncut_part(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    cut(db, rid, alloc, 200)
    supersede(db, issued600["mat"])
    r = ret(db, rid, alloc, 400)
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == (0, 200, 800)
    assert r.allocation_status == "PARTIALLY_CONSUMED"                     # consumed history is preserved
    assert_reconciled(db, unit)


def test_partial_return_on_a_superseded_routing_keeps_the_allocation_issued(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    supersede(db, issued600["mat"])
    assert ret(db, rid, alloc, 250).allocation_status == "ISSUED"


def test_invalid_routing_lifecycle_states_are_rejected(issued600):
    db, alloc, rid = issued600["db"], issued600["alloc"], issued600["rid"]
    db.query(Routing).one().status = "DRAFT"
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "DRAFT" in e.value.detail and snapshot(db) == before
    db.query(Routing).one().status = "ACTIVE"
    db.query(Routing).one().material_source = "F1_PRODUCTION"
    db.commit()
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "CONTINUOUS_CASTING" in e.value.detail


@pytest.mark.parametrize("state", [WOStatus.CLOSED, WOStatus.DISPATCHED])
def test_a_closed_work_order_can_still_hand_its_issued_stock_back(issued600, state):
    db = issued600["db"]
    fresh(db, WorkOrder, issued600["wo"].id).status = state
    db.commit()
    assert ret(db, issued600["rid"], issued600["alloc"], 600).unit_issued_length_mm == 0


# ------------------------------------------------------------------ identity
def test_mismatched_routing_is_rejected(issued600):
    db, alloc = issued600["db"], issued600["alloc"]
    make_wo(db, "WO-1002")
    other = new_routing(db, issued600["mat"], "WO-1002")
    before = snapshot(db)
    for bogus in (uuid.uuid4(), other):
        with pytest.raises(HTTPException) as e:
            ret(db, bogus, alloc, 100)
        assert e.value.status_code == 400 and "does not belong" in e.value.detail
    assert snapshot(db) == before


def test_mismatched_allocation_is_rejected(issued600):
    db, rid = issued600["db"], issued600["rid"]
    make_wo(db, "WO-1002")
    other_rid = new_routing(db, issued600["mat"], "WO-1002")
    (u2,) = accepted_units(db, issued600["mat"], [500])
    other = allocate(db, other_rid, u2, 500)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        ret(db, rid, other, 10)
    assert e.value.status_code == 400 and "does not belong" in e.value.detail
    with pytest.raises(HTTPException) as e:
        Rsv.return_stock(db, CCReturnCreate(routing_id=rid, allocation_id=uuid.uuid4(), stock_unit_id=u2.id,
                                            inward_id=u2.inward_id, length_mm=10), _user(db, UserRole.STORE))
    assert e.value.status_code == 404 and snapshot(db) == before


def test_mismatched_stock_unit_is_rejected(issued600):
    db, alloc, rid = issued600["db"], issued600["alloc"], issued600["rid"]
    (other,) = accepted_units(db, issued600["mat"], [900])
    before = snapshot(db)
    for bogus in (other.id, uuid.uuid4()):
        with pytest.raises(HTTPException) as e:
            ret(db, rid, alloc, 100, unit_id=bogus)
        assert e.value.status_code == 400 and "not the unit allocated" in e.value.detail
    assert snapshot(db) == before


def test_inward_identity_mismatch_is_rejected(issued600):
    db, alloc, rid = issued600["db"], issued600["alloc"], issued600["rid"]
    (other,) = accepted_units(db, issued600["mat"], [900])               # a second receipt, a different inward
    before = snapshot(db)
    for bogus in (other.inward_id, uuid.uuid4()):
        with pytest.raises(HTTPException) as e:
            ret(db, rid, alloc, 100, inward_id=bogus)
        assert e.value.status_code == 400 and "not the inward" in e.value.detail
    assert snapshot(db) == before


def test_every_identity_field_is_required(issued600):
    db, alloc, rid = issued600["db"], issued600["alloc"], issued600["rid"]
    base = dict(routing_id=rid, allocation_id=alloc.id, stock_unit_id=alloc.stock_unit_id,
                inward_id=issued600["unit"].inward_id, length_mm=10)
    for missing in ("routing_id", "allocation_id", "stock_unit_id", "inward_id"):
        data = dict(base)
        del data[missing]
        with pytest.raises(ValidationError):
            CCReturnCreate(**data)
        data[missing], data["reason"] = None, None
        with pytest.raises(HTTPException) as e:
            Rsv.return_stock(db, CCReturnCreate.model_construct(**data), _user(db, UserRole.STORE))
        assert e.value.status_code == 400 and "required" in e.value.detail


def test_no_idempotency_or_qa_field_exists(issued600):
    alloc = issued600["alloc"]
    for extra in ({"client_request_id": "x"}, {"qa_status": "ACCEPTED"}):
        with pytest.raises(ValidationError):
            CCReturnCreate(routing_id=issued600["rid"], allocation_id=alloc.id, stock_unit_id=alloc.stock_unit_id,
                           inward_id=issued600["unit"].inward_id, length_mm=10, **extra)


# ------------------------------------------------------------------ what RETURN must not touch
def test_physical_piece_count_and_the_receipt_are_unchanged(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    inward_before, units_before = rows(db, "cc_inwards"), count(db, "cc_stock_units")
    for x in (150, 150, 300):
        r = ret(db, rid, alloc, x)
        row = db.query(Ledger).filter_by(transaction_number=r.ledger_transaction_number).one()
        assert row.piece_qty is None
    assert rows(db, "cc_inwards") == inward_before and count(db, "cc_stock_units") == units_before
    assert db.query(Inward).one().received_piece_count == 1
    u = fresh(db, Unit, unit.id)
    assert u.original_length_mm == 1000 and u.parent_unit_id is None       # same unit, original length intact
    for value in (u.original_length_mm, u.remaining_length_mm, u.reserved_length_mm, u.issued_length_mm,
                  u.consumed_length_mm):
        assert type(value) is int


def test_reserved_balance_is_unchanged_by_a_return(mixed):
    db, unit, alloc, rid = mixed["db"], mixed["unit"], mixed["alloc"], mixed["rid"]      # reserved 400, issued 600
    r = ret(db, rid, alloc, 250)
    assert (r.unit_reserved_length_mm, r.allocation_reserved_length_mm) == (400, 400)
    assert (r.unit_issued_length_mm, r.allocation_issued_length_mm) == (350, 350)
    assert r.unit_remaining_length_mm == 1000 and r.unit_free_length_mm == 250
    assert_reconciled(db, unit)


def test_consumed_balance_is_unchanged_by_a_return(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    cut(db, rid, alloc, 150)
    before = (fresh(db, Unit, unit.id).consumed_length_mm, fresh(db, Alloc, alloc.id).consumed_length_mm)
    ret(db, rid, alloc, 100)
    ret(db, rid, alloc, 350)
    assert (fresh(db, Unit, unit.id).consumed_length_mm, fresh(db, Alloc, alloc.id).consumed_length_mm) == before == (150, 150)


def test_return_leaves_the_oms_untouched(issued600):
    db, alloc, rid = issued600["db"], issued600["alloc"], issued600["rid"]
    before = oms_state(db)
    ret(db, rid, alloc, 200)
    supersede(db, issued600["mat"])
    ret(db, rid, alloc, 400)
    assert oms_state(db) == before                                         # WO, WORoute, StageWIP, movements ...
    for table in ("production_movements", "production_updates", "nc_records"):
        assert count(db, table) == 0
    assert count(db, "stage_wips") == 1 and count(db, "wo_routes") == 3 and count(db, "work_orders") == 1


# ------------------------------------------------------------------ ledger
def test_exactly_one_return_row_and_history_is_untouched(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    cut(db, rid, alloc, 200)
    history = rows(db, "cc_stock_ledger")                                  # INWARD, RESERVE, ISSUE, CUT_CONSUME
    user = _user(db, UserRole.STORE)
    r = ret(db, rid, alloc, 300, user=user, reason="Back to the rack")
    assert count(db, "cc_stock_ledger") == len(history) + 1
    assert db.query(Ledger).filter_by(movement_type="RETURN").count() == 1
    row = db.query(Ledger).filter_by(transaction_number=r.ledger_transaction_number).one()
    assert row.movement_type == "RETURN" and row.length_mm == 300 and row.piece_qty is None
    assert row.inward_id == unit.inward_id and row.stock_unit_id == unit.id and row.allocation_id == alloc.id
    assert row.unit_remaining_after_mm == 800                               # unchanged by the return
    assert row.performed_by_id == user.id and row.performed_by_name == user.full_name
    assert row.reason == "Back to the rack" and row.client_request_id is None and row.created_at is not None
    assert alloc.allocation_number in row.reference and "WO-1001" in row.reference and "routing v1" in row.reference
    assert db.get(Routing, db.get(Alloc, row.allocation_id).routing_id).work_order.wo_number == "WO-1001"
    assert db.query(AuditLog).filter(AuditLog.action == "CC_RETURN").one().entity_id == alloc.allocation_number
    after = rows(db, "cc_stock_ledger")
    assert [r_ for r_ in after if r_ in history] == history                 # ISSUE and CUT_CONSUME rows byte-identical
    types = {t for (t,) in db.query(Ledger.movement_type).all()}
    assert types == {"INWARD", "RESERVE", "ISSUE", "CUT_CONSUME", "RETURN"}
    row.reason = "tamper"
    with pytest.raises(ValueError):
        db.flush()
    db.rollback()


def test_default_reason(issued600):
    r = ret(issued600["db"], issued600["rid"], issued600["alloc"], 10)
    assert "Return from WO-1001 routing v1" in issued600["db"].query(Ledger).filter_by(
        transaction_number=r.ledger_transaction_number).one().reason


# ------------------------------------------------------------------ lifecycle combinations
def test_partial_return_followed_by_another_issue(mixed):
    db, unit, alloc, rid = mixed["db"], mixed["unit"], mixed["alloc"], mixed["rid"]   # reserved 400, issued 600
    ret(db, rid, alloc, 200)                                                # issued 400, free 200
    r = issue(db, rid, alloc, 200)                                          # reserved 200, issued 600
    assert (r.allocation_reserved_length_mm, r.allocation_issued_length_mm) == (200, 600)
    assert (r.unit_reserved_length_mm, r.unit_issued_length_mm, r.unit_remaining_length_mm) == (200, 600, 1000)
    assert_reconciled(db, unit)


def test_full_return_then_a_whole_new_reserve_issue_lifecycle(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    ret(db, rid, alloc, 600)
    assert fresh(db, Alloc, alloc.id).status == "PLANNED"
    assert reserve(db, rid, alloc, 700).allocation_status == "RESERVED"
    r = issue(db, rid, alloc, 700)
    assert (r.unit_issued_length_mm, r.unit_reserved_length_mm, r.unit_remaining_length_mm) == (700, 0, 1000)
    c = cut(db, rid, alloc, 300)
    assert (c.unit_consumed_length_mm, c.unit_remaining_length_mm, c.unit_issued_length_mm) == (300, 700, 400)
    assert_reconciled(db, unit)
    t = ledger_totals(db, unit.id)
    assert t["RETURN"] == 600 and t["ISSUE"] == 1300 and t["RESERVE"] == 1300


def test_the_plan_total_only_ever_falls_on_a_return(mixed):
    db, alloc, rid = mixed["db"], mixed["alloc"], mixed["rid"]
    def total():
        a = fresh(db, Alloc, alloc.id)
        return a.reserved_length_mm + a.issued_length_mm + a.consumed_length_mm
    assert total() == 1000
    ret(db, rid, alloc, 100)
    assert total() == 900 <= 1000                                          # reserved + issued + consumed <= planned
    reserve(db, rid, alloc, 100)                                           # and the freed plan can be reserved again
    assert total() == 1000


# ------------------------------------------------------------------ roles
@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STORE])
def test_return_roles_allowed(issued600, role):
    db = issued600["db"]
    assert ret(db, issued600["rid"], issued600["alloc"], 100, user=_user(db, role)).success


@pytest.mark.parametrize("role", [UserRole.PLANNER, UserRole.PRODUCTION_MANAGER, UserRole.ENGINEERING, UserRole.QA,
                                  UserRole.DISPATCH, UserRole.CEO, UserRole.MACHINE_OPERATOR])
def test_other_roles_cannot_return(issued600, role):
    db = issued600["db"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        ret(db, issued600["rid"], issued600["alloc"], 100, user=_user(db, role))
    assert e.value.status_code == 403 and snapshot(db) == before


def test_anonymous_cannot_return(issued600):
    alloc = issued600["alloc"]
    with pytest.raises(HTTPException) as e:
        Rsv.return_stock(issued600["db"], CCReturnCreate(
            routing_id=issued600["rid"], allocation_id=alloc.id, stock_unit_id=alloc.stock_unit_id,
            inward_id=issued600["unit"].inward_id, length_mm=10), None)
    assert e.value.status_code == 403


def test_return_is_a_stores_step_the_planner_can_release_but_not_return(issued600):
    db, alloc, rid = issued600["db"], issued600["alloc"], issued600["rid"]
    planner = _user(db, UserRole.PLANNER)
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 10, user=planner)
    assert e.value.status_code == 403
    reserve(db, rid, alloc, 100, user=planner)
    assert release(db, rid, alloc, 100, user=planner).success


# ------------------------------------------------------------------ reconciliation / drift
def test_reconciliation_after_every_successful_return(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    for x in (100, 50, 200, 250):
        ret(db, rid, alloc, x)
        assert_reconciled(db, unit)
    t = ledger_totals(db, unit.id)
    assert fresh(db, Unit, unit.id).issued_length_mm == t["ISSUE"] - t["RETURN"] - t.get("CUT_CONSUME", 0) == 0


@pytest.mark.parametrize("what", ["unit_issued", "unit_consumed", "unit_reserved",
                                  "alloc_issued", "alloc_consumed", "alloc_reserved"])
def test_deliberate_cache_drift_is_detected_and_rolled_back(mixed, what):
    db, unit, alloc, rid = mixed["db"], mixed["unit"], mixed["alloc"], mixed["rid"]
    cut(db, rid, alloc, 100)                          # reserved 400, issued 500, consumed 100, remaining 900
    u, a = fresh(db, Unit, unit.id), fresh(db, Alloc, alloc.id)
    {"unit_issued": lambda: setattr(u, "issued_length_mm", u.issued_length_mm - 50),
     "unit_consumed": lambda: setattr(u, "consumed_length_mm", u.consumed_length_mm - 50),
     "unit_reserved": lambda: setattr(u, "reserved_length_mm", u.reserved_length_mm - 50),
     "alloc_issued": lambda: setattr(a, "issued_length_mm", a.issued_length_mm - 50),
     "alloc_consumed": lambda: setattr(a, "consumed_length_mm", a.consumed_length_mm - 50),
     "alloc_reserved": lambda: setattr(a, "reserved_length_mm", a.reserved_length_mm - 50)}[what]()
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 100)
    assert e.value.status_code == 500 and "reconcil" in e.value.detail.lower()
    assert snapshot(db) == before                                           # nothing partial survived


def test_a_unit_issued_below_its_allocation_is_a_controlled_500_before_any_change(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    u = fresh(db, Unit, unit.id)
    u.issued_length_mm = 100                                               # drift: allocation says 600
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 200)
    assert e.value.status_code == 500 and "issued balance is lower than its allocation's" in e.value.detail
    assert snapshot(db) == before


def test_a_ledger_that_disagrees_with_the_balances_rolls_everything_back(issued600):
    db, alloc, rid = issued600["db"], issued600["alloc"], issued600["rid"]
    before = snapshot(db)

    def skew(mapper, connection, target):
        target.length_mm = target.length_mm + 1

    event.listen(Ledger, "before_insert", skew)
    try:
        with pytest.raises(HTTPException) as e:
            ret(db, rid, alloc, 100)
    finally:
        event.remove(Ledger, "before_insert", skew)
    assert e.value.status_code == 500 and snapshot(db) == before
    assert ret(db, rid, alloc, 100).reconciled is True


def test_the_database_check_constraints_still_back_the_return_up(issued600):
    db, unit = issued600["db"], issued600["unit"]
    u = fresh(db, Unit, unit.id)
    u.issued_length_mm = -1
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ------------------------------------------------------------------ locking + stale reads
def test_return_locks_unit_then_allocation_then_routing(issued600, monkeypatch):
    order = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    ret(issued600["db"], issued600["rid"], issued600["alloc"], 100)
    assert order == [Unit, Alloc, Routing]


def test_balances_are_re_read_after_the_lock(issued600):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    store = _user(db, UserRole.STORE)          # create users BEFORE caching: a commit would expire the "stale" copies
    inward_id, unit_id = unit.inward_id, unit.id
    stale_u, stale_a = db.get(Unit, unit.id), db.get(Alloc, alloc.id)
    assert (stale_u.issued_length_mm, stale_a.issued_length_mm) == (600, 600)
    a_t, u_t = Base.metadata.tables["cc_allocations"], Base.metadata.tables["cc_stock_units"]
    db.execute(a_t.update().where(a_t.c.id == str(alloc.id)).values(issued_length_mm=100))
    db.execute(u_t.update().where(u_t.c.id == str(unit.id)).values(issued_length_mm=100))
    assert (stale_u.issued_length_mm, stale_a.issued_length_mm) == (600, 600)        # really stale
    with pytest.raises(HTTPException) as e:
        Rsv.return_stock(db, CCReturnCreate(routing_id=rid, allocation_id=alloc.id, stock_unit_id=unit_id,
                                            inward_id=inward_id, length_mm=200), store)
    assert e.value.status_code == 400 and "only 100 mm is currently issued" in e.value.detail


def test_two_connections_cannot_return_more_than_is_issued(shared):
    s1, s2 = shared
    mat = _material(s1)
    make_wo(s1, "WO-1001")
    (unit,) = accepted_units(s1, mat, [1000])
    rid = new_routing(s1, mat)
    alloc = allocate(s1, rid, unit, 1000)
    reserve(s1, rid, alloc, 600), issue(s1, rid, alloc, 600)
    aid, uid, iid = alloc.id, unit.id, unit.inward_id
    st1 = _user(s1, UserRole.STORE)
    st2 = s2.get(User, st1.id)
    stale_u, stale_a = s2.get(Unit, uid), s2.get(Alloc, aid)                # connection B caches both rows
    assert (stale_u.issued_length_mm, stale_a.issued_length_mm) == (600, 600)
    Rsv.return_stock(s1, CCReturnCreate(routing_id=rid, allocation_id=aid, stock_unit_id=uid, inward_id=iid,
                                        length_mm=500), st1)
    assert (stale_u.issued_length_mm, stale_a.issued_length_mm) == (600, 600)        # stale in B; truth is 100
    with pytest.raises(HTTPException) as e:
        Rsv.return_stock(s2, CCReturnCreate(routing_id=rid, allocation_id=aid, stock_unit_id=uid, inward_id=iid,
                                            length_mm=300), st2)
    assert e.value.status_code == 400 and "only 100 mm" in e.value.detail
    Rsv.return_stock(s2, CCReturnCreate(routing_id=rid, allocation_id=aid, stock_unit_id=uid, inward_id=iid,
                                        length_mm=100), st2)
    s1.expire_all()
    final = s1.get(Unit, uid)
    assert (final.issued_length_mm, final.remaining_length_mm, final.consumed_length_mm) == (0, 1000, 0)
    assert_reconciled(s1, final)


# ------------------------------------------------------------------ atomicity
@pytest.mark.parametrize("model,event_name", [(Ledger, "before_insert"), (Unit, "after_update"),
                                              (Alloc, "after_update")])
def test_rollback_after_a_mid_transaction_failure(issued600, model, event_name):
    """Ledger insert failure, unit update failure, allocation update failure: nothing partial remains."""
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    before = snapshot(db)
    off = _raising_listener(model, event_name)
    try:
        with pytest.raises(RuntimeError):
            ret(db, rid, alloc, 250)
    finally:
        off()
    assert snapshot(db) == before
    assert_reconciled(db, unit)
    assert ret(db, rid, alloc, 250).reconciled is True


def test_commit_time_failure_rolls_everything_back(issued600, monkeypatch):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    store = _user(db, UserRole.STORE)
    before = snapshot(db)
    seen = {}

    def failing_commit():
        seen["ledger_rows_in_tx"] = count(db, "cc_stock_ledger")             # the RETURN row IS in the transaction
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        Rsv.return_stock(db, CCReturnCreate(routing_id=rid, allocation_id=alloc.id, stock_unit_id=alloc.stock_unit_id,
                                            inward_id=unit.inward_id, length_mm=100), store)
    monkeypatch.undo()
    assert seen["ledger_rows_in_tx"] == len(before["cc_stock_ledger"]) + 1
    assert snapshot(db) == before
    assert_reconciled(db, unit)


def test_rollback_after_everything_was_flushed(issued600, monkeypatch):
    db, alloc, rid = issued600["db"], issued600["alloc"], issued600["rid"]
    before = snapshot(db)

    def late(*a, **k):
        raise RuntimeError("late failure")

    monkeypatch.setattr(rv_svc, "CCStockMovementResult", late)
    with pytest.raises(RuntimeError):
        ret(db, rid, alloc, 100)
    assert snapshot(db) == before


# ------------------------------------------------------------------ numbering
def test_ledger_number_collision_is_retried_and_recovers(issued600, monkeypatch):
    db, unit, alloc, rid = issued600["db"], issued600["unit"], issued600["alloc"], issued600["rid"]
    calls = _flaky(monkeypatch, ["TXN-000001"])                              # already used by the INWARD row
    r = ret(db, rid, alloc, 100)
    assert len(calls) == 2 and r.ledger_transaction_number == "TXN-000004"
    assert db.query(Ledger).filter_by(movement_type="RETURN").count() == 1
    assert_reconciled(db, unit)


def test_persistent_collision_is_a_controlled_409_with_nothing_changed(issued600, monkeypatch):
    db, alloc, rid = issued600["db"], issued600["alloc"], issued600["rid"]
    before = snapshot(db)
    calls = _flaky(monkeypatch, ["TXN-000001"] * 10)
    with pytest.raises(HTTPException) as e:
        ret(db, rid, alloc, 100)
    assert e.value.status_code == 409 and len(calls) == rv_svc.CC_NUMBER_MAX_ATTEMPTS
    assert snapshot(db) == before


# ------------------------------------------------------------------ randomized legitimate sequence
def test_random_legitimate_sequences_with_a_supersession_keep_every_invariant(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    rng = random.Random(20261005)
    ops = {"reserve": reserve, "issue": issue, "cut": cut, "return": ret, "release": release}
    accepted = {k: 0 for k in ops}
    rejected = 0
    for step in range(320):
        if step == 160:
            supersede(db, w1000["mat"])                    # from here only RETURN and RELEASE can succeed
        name, x = rng.choice(list(ops)), rng.randint(1, 350)
        try:
            ops[name](db, rid, alloc, x)
            accepted[name] += 1
            if step >= 160:
                assert name in ("return", "release"), name
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
    assert all(n > 0 for n in accepted.values()), accepted                  # every operation, RETURN included, ran
    assert rejected > 30
    t = ledger_totals(db, unit.id)
    u = fresh(db, Unit, unit.id)
    assert u.consumed_length_mm == t.get("CUT_CONSUME", 0)
    assert u.issued_length_mm == t.get("ISSUE", 0) - t.get("RETURN", 0) - t.get("CUT_CONSUME", 0)
