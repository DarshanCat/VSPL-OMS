"""Continuous Casting SPLIT_OUT / SPLIT_IN (Phase 8). In-memory SQLite only; no database file.

A split moves FREE length from a parent unit to one new child unit (a retained remnant):
parent remaining - X (reserved/issued/consumed/original unchanged); child original = remaining = X.
Nothing is consumed and no length is created. SQLite ignores FOR UPDATE, so PostgreSQL row-lock
behaviour is not proven; the lock request/order, the post-lock re-read (two real connections),
rollback and the invariants are.
"""
import random
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query

from app.core.database import Base
from app.models import *  # noqa: F401,F403
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.schemas.continuous_casting import CCSplitCreate
import app.services.continuous_casting_reservation_service as rv_svc
import app.services.continuous_casting_split_service as split_svc
from app.services.continuous_casting_split_service import ContinuousCastingSplitService as Splt

from test_cc_reservation_service import (  # noqa: F401
    db, shared, world, Ledger, Alloc, Unit, Routing, Inward,
    _user, make_wo, _material, accepted_units, new_routing, supersede, allocate, reserve, release,
    _ledger_row, count, rows, oms_state, snapshot, fresh, ledger_totals, assert_reconciled,
    _raising_listener, cc,
)
from test_cc_issue_service import issue  # noqa: F401
from test_cc_cut_consume_service import w1000, cut  # noqa: F401
from test_cc_return_service import ret  # noqa: F401


def split(db, unit, x, user=None, inward_id=None, unit_id=None, **kw):
    return Splt.split(
        db, CCSplitCreate(stock_unit_id=unit_id or unit.id, inward_id=inward_id or unit.inward_id,
                          length_mm=x, **kw),
        user or _user(db, UserRole.STORE))


def child_of(db, result):
    return db.query(Unit).filter_by(unit_number=result.child_unit_number).one()


@pytest.fixture()
def bar(db):
    """One ACCEPTED 1000 mm bar with a location, no routing."""
    mat = _material(db)
    (unit,) = accepted_units(db, mat, [1000])
    unit.location = "RACK-7"
    db.commit()
    return dict(db=db, mat=mat, unit=unit)


def assert_unit_formula(db, unit_id):
    u = fresh(db, Unit, unit_id)
    t = ledger_totals(db, u.id)
    assert u.remaining_length_mm == t.get("INWARD", 0) + t.get("SPLIT_IN", 0) - t.get("SPLIT_OUT", 0) - t.get("CUT_CONSUME", 0)
    assert_reconciled(db, u)


def assert_conserved(db, inward_id, total):
    db.expire_all()
    units = db.query(Unit).filter(Unit.inward_id == inward_id).all()
    assert sum(u.remaining_length_mm + u.consumed_length_mm for u in units) == total
    assert sum(u.original_length_mm for u in units if u.parent_unit_id is None) == total


# ------------------------------------------------------------------ the core semantics
def test_split_1000_into_700_parent_and_300_child(bar):
    db, unit = bar["db"], bar["unit"]
    uid, iid, parent_number = unit.id, unit.inward_id, unit.unit_number
    r = split(db, unit, 300)
    assert r.success and r.reconciled and r.length_mm == 300
    p, c = fresh(db, Unit, uid), child_of(db, r)
    assert (p.remaining_length_mm, p.reserved_length_mm, p.issued_length_mm, p.consumed_length_mm) == (700, 0, 0, 0)
    assert p.original_length_mm == 1000 and p.status == "IN_STOCK" and p.parent_unit_id is None
    assert (c.original_length_mm, c.remaining_length_mm, c.reserved_length_mm, c.issued_length_mm,
            c.consumed_length_mm) == (300, 300, 0, 0, 0)
    assert c.parent_unit_id == uid and c.inward_id == iid and c.status == "IN_STOCK"
    assert c.unit_number != parent_number and c.unit_number.startswith("UNIT-") and c.id != uid
    assert c.location == "RACK-7" and p.location == "RACK-7"
    assert (r.parent_remaining_length_mm, r.parent_free_length_mm, r.child_free_length_mm) == (700, 700, 300)
    assert (r.child_status, r.parent_status, r.child_original_length_mm) == ("IN_STOCK", "IN_STOCK", 300)
    assert r.child_location == "RACK-7" and r.parent_unit_number == parent_number
    assert db.query(Inward).one().received_piece_count == 1                 # the receipt fact is untouched
    assert db.query(Alloc).count() == 0                                      # a split involves no allocation
    assert_conserved(db, iid, 1000)
    assert r.inward_units_remaining_plus_consumed_mm == r.inward_total_length_mm == 1000
    assert_unit_formula(db, uid), assert_unit_formula(db, c.id)


def test_two_immutable_ledger_rows_reference_each_other(bar):
    db, unit = bar["db"], bar["unit"]
    uid, iid = unit.id, unit.inward_id
    history = rows(db, "cc_stock_ledger")
    user = _user(db, UserRole.STORE)
    r = split(db, unit, 300, user=user, reason="Retain remnant")
    c = child_of(db, r)
    assert count(db, "cc_stock_ledger") == len(history) + 2
    out = db.query(Ledger).filter_by(transaction_number=r.split_out_transaction_number).one()
    inn = db.query(Ledger).filter_by(transaction_number=r.split_in_transaction_number).one()
    assert (out.movement_type, out.stock_unit_id, out.related_stock_unit_id) == ("SPLIT_OUT", uid, c.id)
    assert (inn.movement_type, inn.stock_unit_id, inn.related_stock_unit_id) == ("SPLIT_IN", c.id, uid)
    for row, after in ((out, 700), (inn, 300)):
        assert row.length_mm == 300 and row.piece_qty is None and row.allocation_id is None
        assert row.inward_id == iid and row.unit_remaining_after_mm == after
        assert row.performed_by_id == user.id and row.performed_by_name == user.full_name
        assert row.reason == "Retain remnant" and row.client_request_id is None and row.nc_record_id is None
        assert row.reference == f"{r.parent_unit_number} -> {r.child_unit_number}"
    assert out.transaction_number != inn.transaction_number and out.transaction_number < inn.transaction_number
    assert [x for x in rows(db, "cc_stock_ledger") if x in history] == history          # old rows untouched
    audit = db.query(AuditLog).filter(AuditLog.action == "CC_SPLIT").one()
    assert audit.entity_id == r.parent_unit_number and r.child_unit_number in audit.new_value
    out.reason = "tamper"
    with pytest.raises(ValueError):
        db.flush()
    db.rollback()


def test_default_reasons_name_the_other_unit(bar):
    db = bar["db"]
    r = split(db, bar["unit"], 100)
    out = db.query(Ledger).filter_by(transaction_number=r.split_out_transaction_number).one()
    inn = db.query(Ledger).filter_by(transaction_number=r.split_in_transaction_number).one()
    assert r.child_unit_number in out.reason and r.parent_unit_number in inn.reason


def test_a_remnant_traces_back_to_the_original_inward_through_a_chain(bar):
    db, unit = bar["db"], bar["unit"]
    iid, uid = unit.inward_id, unit.id
    c1 = child_of(db, split(db, unit, 400))
    c1id = c1.id
    r2 = split(db, c1, 150)
    c2 = child_of(db, r2)
    assert c2.parent_unit_id == c1id and c2.inward_id == iid and c2.original_length_mm == 150
    assert fresh(db, Unit, c1id).parent_unit_id == uid and fresh(db, Unit, c1id).remaining_length_mm == 250
    out = db.query(Ledger).filter_by(transaction_number=r2.split_out_transaction_number).one()
    assert out.inward_id == iid
    assert db.query(Inward).filter_by(id=iid).one().inward_number == r2.inward_number
    assert_conserved(db, iid, 1000)
    for u in db.query(Unit).all():
        assert_unit_formula(db, u.id)


def test_several_splits_are_explicit_one_child_each(bar):
    db, unit = bar["db"], bar["unit"]
    uid, iid = unit.id, unit.inward_id
    split(db, unit, 300), split(db, unit, 200)
    assert db.query(Unit).count() == 3 and fresh(db, Unit, uid).remaining_length_mm == 500
    assert db.query(Ledger).filter_by(movement_type="SPLIT_OUT").count() == 2
    assert db.query(Ledger).filter_by(movement_type="SPLIT_IN").count() == 2
    assert len({u.unit_number for u in db.query(Unit).all()}) == 3
    assert_conserved(db, iid, 1000)


def test_a_split_never_creates_a_received_piece(bar):
    db, unit = bar["db"], bar["unit"]
    split(db, unit, 100)
    split(db, db.query(Unit).filter(Unit.parent_unit_id.is_(None)).one(), 100)
    assert db.query(Inward).one().received_piece_count == 1 and db.query(Inward).one().received_total_length_mm == 1000
    assert [r.piece_qty for r in db.query(Ledger).filter(Ledger.movement_type.in_(("SPLIT_OUT", "SPLIT_IN")))] == [None] * 4
    assert db.query(Ledger).filter_by(movement_type="INWARD").one().piece_qty == 1


# ------------------------------------------------------------------ interaction with the stock lifecycle
def test_split_after_partial_issue_only_moves_free_length(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    uid = unit.id
    reserve(db, rid, alloc, 1000), issue(db, rid, alloc, 600)               # reserved 400, issued 600 -> free 0
    with pytest.raises(HTTPException) as e:
        split(db, unit, 1)
    assert e.value.status_code == 400 and "only 0 mm is free" in e.value.detail
    release(db, rid, alloc, 400)                                             # free 400
    allocs_before = rows(db, "cc_allocations")
    r = split(db, unit, 300)
    p = fresh(db, Unit, uid)
    assert (p.remaining_length_mm, p.reserved_length_mm, p.issued_length_mm, p.consumed_length_mm) == (700, 0, 600, 0)
    assert rows(db, "cc_allocations") == allocs_before                       # no allocation touched
    with pytest.raises(HTTPException) as e:
        split(db, p, 101)                                                    # only 100 mm is still free
    assert e.value.status_code == 400 and "only 100 mm is free" in e.value.detail
    c = cut(db, rid, alloc, 600)                                             # the issued length is still cuttable
    assert (c.unit_remaining_length_mm, c.unit_issued_length_mm, c.unit_consumed_length_mm) == (100, 0, 600)
    assert_unit_formula(db, uid), assert_unit_formula(db, child_of(db, r).id)
    assert_conserved(db, p.inward_id, 1000)


def test_split_after_partial_cut(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    uid = unit.id
    reserve(db, rid, alloc, 1000), issue(db, rid, alloc, 600), cut(db, rid, alloc, 200)
    release(db, rid, alloc, 400)                  # remaining 800, issued 400, consumed 200, free 400
    r = split(db, unit, 300)
    p = fresh(db, Unit, uid)
    assert (p.remaining_length_mm, p.issued_length_mm, p.consumed_length_mm, p.original_length_mm) == (500, 400, 200, 1000)
    assert r.parent_free_length_mm == 100 and p.status == "IN_STOCK"
    t = ledger_totals(db, uid)
    assert 1000 + t.get("SPLIT_IN", 0) - t["SPLIT_OUT"] - t["CUT_CONSUME"] == 500
    assert_conserved(db, p.inward_id, 1000)
    assert_unit_formula(db, uid)


def test_a_remnant_generated_from_cutting_becomes_a_child_and_the_parent_is_consumed(w1000):
    db, unit, alloc, rid, mat = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"], w1000["mat"]
    uid, iid = unit.id, unit.inward_id
    reserve(db, rid, alloc, 700), issue(db, rid, alloc, 700)
    cut(db, rid, alloc, 700)                                                 # remaining 300, consumed 700
    assert fresh(db, Unit, uid).status == "IN_STOCK" and fresh(db, Unit, uid).remaining_length_mm == 300
    r = split(db, unit, 300)
    p, c = fresh(db, Unit, uid), child_of(db, r)
    assert (p.remaining_length_mm, p.consumed_length_mm, p.status) == (0, 700, "CONSUMED")
    assert (c.remaining_length_mm, c.consumed_length_mm, c.status, c.parent_unit_id) == (300, 0, "IN_STOCK", uid)
    assert r.parent_status == "CONSUMED" and "fully consumed" in r.message
    assert_conserved(db, iid, 1000)
    assert fresh(db, Alloc, alloc.id).status == "PARTIALLY_CONSUMED"          # the allocation is not touched
    # the child is the physical remnant: it can be allocated to another WO, reserved, issued and cut
    make_wo(db, "WO-1002")
    rid2 = new_routing(db, mat, "WO-1002")
    a2 = allocate(db, rid2, c, 300)
    reserve(db, rid2, a2, 300), issue(db, rid2, a2, 300)
    done = cut(db, rid2, a2, 300)
    assert (done.unit_remaining_length_mm, done.unit_consumed_length_mm) == (0, 300)
    assert fresh(db, Unit, c.id).status == "CONSUMED"
    assert_conserved(db, iid, 1000)
    for u in db.query(Unit).all():
        assert_unit_formula(db, u.id)


def test_a_consumed_parent_can_no_longer_be_split_or_cut(w1000):
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    reserve(db, rid, alloc, 700), issue(db, rid, alloc, 700), cut(db, rid, alloc, 700)
    split(db, unit, 300)
    with pytest.raises(HTTPException) as e:
        split(db, unit, 1)
    assert e.value.status_code == 400 and "CONSUMED" in e.value.detail


def test_return_release_and_supersede_interact_correctly_with_a_split(w1000):
    db, unit, alloc, rid, mat = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"], w1000["mat"]
    uid = unit.id
    reserve(db, rid, alloc, 800), issue(db, rid, alloc, 500)                 # reserved 300, issued 500
    ret(db, rid, alloc, 200)                                                 # issued 300 -> free 400
    split(db, unit, 400)
    p = fresh(db, Unit, uid)
    assert (p.remaining_length_mm, p.reserved_length_mm, p.issued_length_mm) == (600, 300, 300)
    supersede(db, mat)                                                       # routing superseded
    with pytest.raises(HTTPException) as e:                                  # free is 0 (reserved 300 + issued 300 = 600)
        split(db, p, 1)
    assert e.value.status_code == 400 and "only 0 mm is free" in e.value.detail
    release(db, rid, alloc, 300)                                             # free 300 again
    assert split(db, fresh(db, Unit, uid), 300).parent_remaining_length_mm == 300
    assert ret(db, rid, alloc, 300).unit_issued_length_mm == 0              # RETURN still works on the superseded routing
    with pytest.raises(HTTPException):
        cut(db, rid, alloc, 1)                                               # CUT_CONSUME still refused
    assert_unit_formula(db, uid)
    assert_conserved(db, p.inward_id, 1000)


def test_split_on_a_superseded_routings_unit_moves_only_free_length(w1000):
    db, unit, alloc, rid, mat = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"], w1000["mat"]
    reserve(db, rid, alloc, 400), supersede(db, mat)
    assert split(db, unit, 600).parent_remaining_length_mm == 400
    with pytest.raises(HTTPException):
        split(db, unit, 1)                                                   # the 400 reserved is not free


# ------------------------------------------------------------------ invalid splits
@pytest.mark.parametrize("bad", [0, -1, 1.5, None, "abc"])
def test_schema_rejects_zero_negative_and_non_integer(bar, bad):
    with pytest.raises(ValidationError):
        CCSplitCreate(stock_unit_id=bar["unit"].id, inward_id=bar["unit"].inward_id, length_mm=bad)


@pytest.mark.parametrize("bad", [0, -1, True])
def test_service_rejects_bad_lengths_without_the_schema(bar, bad):
    db, unit = bar["db"], bar["unit"]
    raw = CCSplitCreate.model_construct(stock_unit_id=unit.id, inward_id=unit.inward_id, length_mm=bad, reason=None)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Splt.split(db, raw, _user(db, UserRole.STORE))
    assert e.value.status_code == 400 and snapshot(db) == before


def test_split_cannot_exceed_free_length_or_the_whole_bar(bar):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)
    for x in (1001, 5000):
        with pytest.raises(HTTPException) as e:
            split(db, unit, x)
        assert e.value.status_code == 400 and "only 1000 mm is free" in e.value.detail
    assert snapshot(db) == before


def test_a_pure_rename_of_the_whole_bar_is_rejected(bar):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        split(db, unit, 1000)
    assert e.value.status_code == 400 and "rename" in e.value.detail
    assert snapshot(db) == before and db.query(Unit).count() == 1
    split(db, unit, 999)                                                     # 1 mm may remain: not a rename


@pytest.mark.parametrize("state", ["ON_HOLD", "SCRAPPED", "CONSUMED"])
def test_only_an_in_stock_unit_can_be_split(bar, state):
    db, unit = bar["db"], bar["unit"]
    unit.status = state
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        split(db, unit, 100)
    assert e.value.status_code == 400 and state in e.value.detail
    assert snapshot(db) == before and db.query(Unit).count() == 1           # no child, so HOLD cannot be bypassed


def test_unknown_unit_is_404(bar):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        split(db, unit, 10, unit_id=uuid.uuid4())
    assert e.value.status_code == 404 and snapshot(db) == before


def test_inward_mismatch_is_rejected(bar):
    db, unit = bar["db"], bar["unit"]
    (other,) = accepted_units(db, bar["mat"], [500])
    before = snapshot(db)
    for bogus in (other.inward_id, uuid.uuid4()):
        with pytest.raises(HTTPException) as e:
            split(db, unit, 10, inward_id=bogus)
        assert e.value.status_code == 400 and "not the inward" in e.value.detail
    assert snapshot(db) == before


def test_required_fields_and_closed_schema(bar):
    db, unit = bar["db"], bar["unit"]
    for missing in ("stock_unit_id", "inward_id"):
        data = dict(stock_unit_id=unit.id, inward_id=unit.inward_id, length_mm=10)
        del data[missing]
        with pytest.raises(ValidationError):
            CCSplitCreate(**data)
        raw = CCSplitCreate.model_construct(stock_unit_id=unit.id, inward_id=unit.inward_id, length_mm=10, reason=None)
        setattr(raw, missing, None)
        with pytest.raises(HTTPException) as e:
            Splt.split(db, raw, _user(db, UserRole.STORE))
        assert e.value.status_code == 400 and "required" in e.value.detail
    for extra in ({"client_request_id": "x"}, {"qa_status": "ACCEPTED"}, {"routing_id": str(uuid.uuid4())},
                  {"allocation_id": str(uuid.uuid4())}, {"piece_qty": 1}, {"location": "X"}):
        with pytest.raises(ValidationError):
            CCSplitCreate(stock_unit_id=unit.id, inward_id=unit.inward_id, length_mm=10, **extra)


# ------------------------------------------------------------------ QA / HOLD / allocation eligibility
def test_pending_qa_stock_may_be_split_but_the_child_is_not_allocatable(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    (unit,) = accepted_units(db, mat, [1000], accept=False)
    rid = new_routing(db, mat)
    r = split(db, unit, 300)
    c = child_of(db, r)
    assert r.child_status == "IN_STOCK"                                      # physically in stock ...
    assert r.child_allocation_eligible is False and "PENDING_QA" in r.child_allocation_ineligible_reason
    with pytest.raises(HTTPException) as e:                                  # ... but the existing gate still blocks it
        allocate(db, rid, c, 100)
    assert e.value.status_code == 400
    db.query(Inward).one().qa_status = "ACCEPTED"                            # QA lives on the inward only
    db.commit()
    assert allocate(db, rid, c, 100).stock_unit_id == c.id
    assert not hasattr(c, "qa_status")


def test_the_child_of_an_accepted_bar_is_allocation_eligible(bar):
    r = split(bar["db"], bar["unit"], 300)
    assert r.child_allocation_eligible is True and r.child_allocation_ineligible_reason is None


# ------------------------------------------------------------------ roles
@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STORE])
def test_split_roles_allowed(bar, role):
    assert split(bar["db"], bar["unit"], 100, user=_user(bar["db"], role)).success


@pytest.mark.parametrize("role", [UserRole.PLANNER, UserRole.PRODUCTION_MANAGER, UserRole.ENGINEERING, UserRole.QA,
                                  UserRole.DISPATCH, UserRole.CEO, UserRole.MACHINE_OPERATOR])
def test_other_roles_cannot_split(bar, role):
    db, unit = bar["db"], bar["unit"]
    who = _user(db, role)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        split(db, unit, 100, user=who)
    assert e.value.status_code == 403 and snapshot(db) == before


def test_anonymous_cannot_split(bar):
    db, unit = bar["db"], bar["unit"]
    with pytest.raises(HTTPException) as e:
        Splt.split(db, CCSplitCreate(stock_unit_id=unit.id, inward_id=unit.inward_id, length_mm=10), None)
    assert e.value.status_code == 403


# ------------------------------------------------------------------ reconciliation
def test_reconciliation_after_every_split_in_a_chain(bar):
    db, unit = bar["db"], bar["unit"]
    target = unit
    for x in (400, 200, 100):                       # each child is split again: 600+400, 400 -> 200+200, 200 -> 100+100
        r = split(db, target, x)
        assert r.reconciled
        for u in db.query(Unit).all():
            assert_unit_formula(db, u.id)
        assert_conserved(db, unit.inward_id, 1000)
        target = child_of(db, r)


def test_reconcile_inward_is_root_only_and_checks_conservation(bar):
    db, unit = bar["db"], bar["unit"]
    iid = unit.inward_id
    split(db, unit, 300)
    inward = db.query(Inward).filter_by(id=iid).one()
    assert split_svc.reconcile_inward(db, inward) == 1000                    # the child's 300 is not a second receipt
    u = db.query(Unit).filter(Unit.parent_unit_id.is_(None)).one()
    u.remaining_length_mm -= 10
    db.flush()
    with pytest.raises(HTTPException) as e:
        split_svc.reconcile_inward(db, inward)
    assert e.value.status_code == 500 and "does not conserve length" in e.value.detail
    db.rollback()


def test_reconcile_inward_detects_unbalanced_split_rows(bar):
    """Unit balances and the receipt still agree; only SPLIT_OUT != SPLIT_IN is wrong."""
    db, unit = bar["db"], bar["unit"]
    (other,) = accepted_units(db, bar["mat"], [500])
    split(db, unit, 300)
    inward = db.query(Inward).filter_by(id=unit.inward_id).one()
    db.add(Ledger(transaction_number=cc.next_cc_ledger_transaction_number(db), movement_type="SPLIT_OUT",
                  inward_id=inward.id, stock_unit_id=unit.id, related_stock_unit_id=other.id, length_mm=5))
    db.flush()
    with pytest.raises(HTTPException) as e:
        split_svc.reconcile_inward(db, inward)
    assert e.value.status_code == 500 and "SPLIT_OUT and SPLIT_IN lengths differ" in e.value.detail
    db.rollback()


def test_the_split_pair_check_detects_an_orphan_split_row(bar):
    db, unit = bar["db"], bar["unit"]
    (other,) = accepted_units(db, bar["mat"], [500])
    r = split(db, unit, 300)
    p, c = fresh(db, Unit, unit.id), child_of(db, r)
    split_svc._reconcile_split(db, p, c, 300)                                # consistent: passes
    db.add(Ledger(transaction_number=cc.next_cc_ledger_transaction_number(db), movement_type="SPLIT_OUT",
                  inward_id=p.inward_id, stock_unit_id=p.id, related_stock_unit_id=other.id, length_mm=5))
    db.flush()
    with pytest.raises(HTTPException) as e:
        split_svc._reconcile_split(db, p, c, 300)
    assert e.value.status_code == 500 and "differs from its children" in e.value.detail
    db.rollback()
    c = child_of(db, r)
    c.parent_unit_id = other.id
    db.flush()
    with pytest.raises(HTTPException) as e:
        split_svc._reconcile_split(db, fresh(db, Unit, unit.id), c, 300)
    assert e.value.status_code == 500
    db.rollback()


@pytest.mark.parametrize("what", ["unit_remaining", "unit_reserved", "unit_issued", "inward_total"])
def test_deliberate_drift_blocks_the_split_and_rolls_back(bar, what):
    db, unit = bar["db"], bar["unit"]
    u = fresh(db, Unit, unit.id)
    if what == "unit_remaining":
        u.remaining_length_mm -= 50
    elif what == "unit_reserved":
        u.reserved_length_mm += 50
    elif what == "unit_issued":
        u.issued_length_mm += 50
    else:
        db.query(Inward).one().received_total_length_mm += 100
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        split(db, unit, 100)
    assert e.value.status_code == 500 and snapshot(db) == before and db.query(Unit).count() == 1


def test_remaining_drift_is_now_caught_by_every_existing_operation(w1000):
    """The strengthened reconciliation: a cached remaining that disagrees with the ledger blocks RESERVE."""
    db, unit, alloc, rid = w1000["db"], w1000["unit"], w1000["alloc"], w1000["rid"]
    fresh(db, Unit, unit.id).remaining_length_mm -= 100
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        reserve(db, rid, alloc, 100)
    assert e.value.status_code == 500 and "remaining" in e.value.detail and snapshot(db) == before


def test_a_consumed_status_without_consumption_is_a_reconciliation_failure(bar):
    db, unit = bar["db"], bar["unit"]
    u = fresh(db, Unit, unit.id)
    u.status = "CONSUMED"                                                    # remaining 1000, consumed 0
    with pytest.raises(HTTPException) as e:
        rv_svc._reconcile(db, u)
    assert e.value.status_code == 500 and "not exhausted by consumption" in e.value.detail
    db.rollback()


def test_a_ledger_that_disagrees_with_the_split_rolls_everything_back(bar):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)
    from sqlalchemy import event

    def skew(mapper, connection, target):
        if target.movement_type == "SPLIT_IN":
            target.length_mm = target.length_mm + 1

    event.listen(Ledger, "before_insert", skew)
    try:
        with pytest.raises(HTTPException) as e:
            split(db, unit, 100)
    finally:
        event.remove(Ledger, "before_insert", skew)
    assert e.value.status_code == 500 and snapshot(db) == before
    assert split(db, unit, 100).reconciled


def test_a_split_out_row_naming_the_wrong_unit_is_caught_by_the_pair_check(bar):
    """Every balance still reconciles; only the SPLIT_OUT <-> SPLIT_IN pairing is wrong."""
    db, unit = bar["db"], bar["unit"]
    (other,) = accepted_units(db, bar["mat"], [500])
    other_id = other.id
    before = snapshot(db)
    from sqlalchemy import event

    def misdirect(mapper, connection, target):
        if target.movement_type == "SPLIT_OUT":
            target.related_stock_unit_id = other_id

    event.listen(Ledger, "before_insert", misdirect)
    try:
        with pytest.raises(HTTPException) as e:
            split(db, unit, 100)
    finally:
        event.remove(Ledger, "before_insert", misdirect)
    assert e.value.status_code == 500 and "matching SPLIT_OUT/SPLIT_IN pair" in e.value.detail
    assert snapshot(db) == before


# ------------------------------------------------------------------ database backstops
def _row(db, unit, mtype, **kw):
    return Ledger(transaction_number=cc.next_cc_ledger_transaction_number(db), movement_type=mtype,
                  inward_id=unit.inward_id, stock_unit_id=unit.id, length_mm=kw.pop("length_mm", 10), **kw)


def test_ledger_split_shape_is_enforced_by_the_database(bar):
    db, unit = bar["db"], bar["unit"]
    (other,) = accepted_units(db, bar["mat"], [500])
    bad = {
        "SPLIT_OUT without related": lambda: _row(db, unit, "SPLIT_OUT"),
        "RESERVE with related": lambda: _row(db, unit, "RESERVE", related_stock_unit_id=other.id),
        "SPLIT_IN with piece_qty": lambda: _row(db, unit, "SPLIT_IN", related_stock_unit_id=other.id, piece_qty=1),
        "SPLIT_OUT related to itself": lambda: _row(db, unit, "SPLIT_OUT", related_stock_unit_id=unit.id),
        "SPLIT_IN of zero length": lambda: _row(db, unit, "SPLIT_IN", related_stock_unit_id=other.id, length_mm=0),
    }
    for name, make in bad.items():
        db.add(make())
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    db.add(_row(db, unit, "SPLIT_OUT", related_stock_unit_id=other.id))       # a well-formed row is accepted
    db.flush()
    db.rollback()


def test_a_unit_can_receive_only_one_split_in_and_cannot_be_its_own_parent(bar):
    db, unit = bar["db"], bar["unit"]
    r = split(db, unit, 100)
    c = child_of(db, r)
    db.add(_row(db, c, "SPLIT_IN", related_stock_unit_id=unit.id))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    u = fresh(db, Unit, unit.id)
    u.parent_unit_id = u.id
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ------------------------------------------------------------------ locking and stale reads
def test_split_locks_only_the_parent_unit(bar, monkeypatch):
    order = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    split(bar["db"], bar["unit"], 100)
    assert order == [Unit]                                                   # no allocation/routing, no second unit


def test_the_parent_is_re_read_after_the_lock(bar):
    db, unit = bar["db"], bar["unit"]
    store = _user(db, UserRole.STORE)          # users first: a commit would expire the "stale" copy
    uid, iid = unit.id, unit.inward_id
    stale = db.get(Unit, uid)
    assert stale.remaining_length_mm == 1000
    t = Base.metadata.tables["cc_stock_units"]
    db.execute(t.update().where(t.c.id == str(uid)).values(remaining_length_mm=500))
    assert stale.remaining_length_mm == 1000                                 # really stale
    with pytest.raises(HTTPException) as e:
        Splt.split(db, CCSplitCreate(stock_unit_id=uid, inward_id=iid, length_mm=600), store)
    assert e.value.status_code == 400 and "only 500 mm is free" in e.value.detail


def test_two_connections_cannot_split_the_same_free_length_twice(shared):
    s1, s2 = shared
    mat = _material(s1)
    (unit,) = accepted_units(s1, mat, [1000])
    uid, iid = unit.id, unit.inward_id
    st1 = _user(s1, UserRole.STORE)
    st2 = s2.get(User, st1.id)
    stale = s2.get(Unit, uid)
    assert stale.remaining_length_mm == 1000
    Splt.split(s1, CCSplitCreate(stock_unit_id=uid, inward_id=iid, length_mm=600), st1)
    assert stale.remaining_length_mm == 1000                                 # stale in B; truth is 400
    with pytest.raises(HTTPException) as e:
        Splt.split(s2, CCSplitCreate(stock_unit_id=uid, inward_id=iid, length_mm=600), st2)
    assert e.value.status_code == 400 and "only 400 mm is free" in e.value.detail
    Splt.split(s2, CCSplitCreate(stock_unit_id=uid, inward_id=iid, length_mm=400 - 1), st2)
    s1.expire_all()
    assert s1.get(Unit, uid).remaining_length_mm == 1
    assert_conserved(s1, iid, 1000)


# ------------------------------------------------------------------ atomicity
@pytest.mark.parametrize("model_name,event_name", [
    ("Ledger", "before_insert"), ("Unit", "before_insert"), ("Unit", "after_update"), ("AuditLog", "before_insert")])
def test_rollback_after_a_mid_transaction_failure(bar, model_name, event_name):
    """Ledger-insert, child-insert, parent-update and audit failures leave nothing behind."""
    db, unit = bar["db"], bar["unit"]
    model = {"Ledger": Ledger, "Unit": Unit, "AuditLog": AuditLog}[model_name]
    before = snapshot(db)
    off = _raising_listener(model, event_name)
    try:
        with pytest.raises(RuntimeError):
            split(db, unit, 300)
    finally:
        off()
    assert snapshot(db) == before and db.query(Unit).count() == 1
    assert split(db, unit, 300).reconciled                                   # and the retry is clean


def test_commit_time_failure_rolls_everything_back(bar, monkeypatch):
    db, unit = bar["db"], bar["unit"]
    store = _user(db, UserRole.STORE)
    req = CCSplitCreate(stock_unit_id=unit.id, inward_id=unit.inward_id, length_mm=300)
    before = snapshot(db)
    seen = {}

    def failing_commit():
        seen["units"], seen["rows"] = count(db, "cc_stock_units"), count(db, "cc_stock_ledger")
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        Splt.split(db, req, store)
    monkeypatch.undo()
    assert seen == {"units": 2, "rows": len(before["cc_stock_ledger"]) + 2}   # everything was in the transaction
    assert snapshot(db) == before


def test_rollback_after_everything_was_flushed(bar, monkeypatch):
    db, unit = bar["db"], bar["unit"]
    before = snapshot(db)

    def late(*a, **k):
        raise RuntimeError("late failure")

    monkeypatch.setattr(split_svc, "CCSplitResult", late)
    with pytest.raises(RuntimeError):
        split(db, unit, 100)
    assert snapshot(db) == before


# ------------------------------------------------------------------ numbering
def test_unit_number_collision_is_retried_and_recovers(bar, monkeypatch):
    db, unit = bar["db"], bar["unit"]
    taken, real, calls = unit.unit_number, split_svc.next_cc_unit_number, []

    def fake(session):
        calls.append(1)
        return taken if len(calls) == 1 else real(session)

    monkeypatch.setattr(split_svc, "next_cc_unit_number", fake)
    r = split(db, unit, 100)
    assert len(calls) == 2 and r.child_unit_number != taken
    assert db.query(Unit).count() == 2


def test_ledger_number_collision_is_retried_and_recovers(bar, monkeypatch):
    db, unit = bar["db"], bar["unit"]
    taken, real, calls = db.query(Ledger).one().transaction_number, split_svc.next_cc_ledger_transaction_numbers, []

    def fake(session, n):
        calls.append(1)
        return [taken, "TXN-900001"] if len(calls) == 1 else real(session, n)

    monkeypatch.setattr(split_svc, "next_cc_ledger_transaction_numbers", fake)
    r = split(db, unit, 100)
    assert len(calls) == 2 and r.split_out_transaction_number != taken
    assert db.query(Ledger).filter_by(movement_type="SPLIT_OUT").count() == 1


def test_persistent_collision_is_a_controlled_409_with_nothing_changed(bar, monkeypatch):
    db, unit = bar["db"], bar["unit"]
    taken, calls = unit.unit_number, []
    before = snapshot(db)

    def fake(session):
        calls.append(1)
        return taken

    monkeypatch.setattr(split_svc, "next_cc_unit_number", fake)
    with pytest.raises(HTTPException) as e:
        split(db, unit, 100)
    assert e.value.status_code == 409 and len(calls) == rv_svc.CC_NUMBER_MAX_ATTEMPTS
    assert snapshot(db) == before


# ------------------------------------------------------------------ isolation
def test_a_split_leaves_the_oms_untouched(w1000):
    db, unit = w1000["db"], w1000["unit"]
    before = oms_state(db)
    split(db, unit, 300)
    assert oms_state(db) == before
    for table in ("production_movements", "production_updates", "nc_records"):
        assert count(db, table) == 0


# ------------------------------------------------------------------ randomized legitimate sequence
def test_random_legitimate_sequences_with_splits_keep_every_invariant(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    (root,) = accepted_units(db, mat, [1000])
    iid, root_id = root.inward_id, root.id
    rid0 = new_routing(db, mat)
    units = [root_id]
    book = {root_id: (rid0, allocate(db, rid0, root, 1000))}
    rng = random.Random(8)
    ok = {k: 0 for k in ("split", "reserve", "issue", "cut", "return", "release")}
    rejected = 0
    ops = {"reserve": reserve, "issue": issue, "cut": cut, "return": ret, "release": release}
    for step in range(300):
        uid, op = rng.choice(units), rng.choice(list(ok))
        cu, ca = fresh(db, Unit, uid), fresh(db, Alloc, book[uid][1].id)
        room = {"split": cu.remaining_length_mm - cu.reserved_length_mm - cu.issued_length_mm,
                "reserve": cu.remaining_length_mm - cu.reserved_length_mm - cu.issued_length_mm,
                "issue": ca.reserved_length_mm, "cut": ca.issued_length_mm, "return": ca.issued_length_mm,
                "release": ca.reserved_length_mm}[op]
        # mostly a legitimate amount; sometimes an arbitrary one (which must be rejected cleanly or be valid)
        x = rng.randint(1, max(1, room)) if rng.random() < 0.85 else rng.randint(1, 420)
        try:
            if op == "split":
                r = split(db, db.get(Unit, uid), x)
                child = child_of(db, r)
                units.append(child.id)
                wo = f"WO-R{len(units)}"
                make_wo(db, wo)
                rid = new_routing(db, mat, wo)
                book[child.id] = (rid, allocate(db, rid, child, child.remaining_length_mm))
            else:
                rid, alloc = book[uid]
                ops[op](db, rid, alloc, x)
            ok[op] += 1
        except HTTPException as e:
            assert e.status_code == 400, e.detail
            rejected += 1
            continue
        for u_id in units:
            u = fresh(db, Unit, u_id)
            assert_unit_formula(db, u_id)
            assert u.reserved_length_mm + u.issued_length_mm <= u.remaining_length_mm
            assert u.remaining_length_mm + u.consumed_length_mm <= u.original_length_mm
            assert u.remaining_length_mm >= 0
            assert (u.status == "CONSUMED") == (u.remaining_length_mm == 0)
            if u.status == "CONSUMED":
                assert u.consumed_length_mm > 0
        assert_conserved(db, iid, 1000)
    assert all(n > 0 for n in ok.values()), ok
    assert ok["split"] >= 5 and rejected > 20
    assert db.query(Inward).one().received_piece_count == 1
