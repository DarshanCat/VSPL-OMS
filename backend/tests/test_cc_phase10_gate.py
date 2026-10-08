"""Continuous Casting cut RESULTS and the China <-> OMS material gate (Phase 10).
In-memory SQLite only; no database file.

Cut result: an immutable record of what one real CUT_CONSUME produced (blanks, cuts, end trim), validated with
the routing's own formula  required = (good + rejected) x blank_length + cuts x kerf + end_trim.
Gate: a WO with an ACTIVE CONTINUOUS_CASTING routing may produce at its FIRST route stage only up to the good
blanks of RECONCILED cut results; applied in ProductionService.record_stage_production and in
ProductionService.move_parts (moving out of the first stage). The gate is read-only and runs before any
mutation. SQLite ignores FOR UPDATE: the lock REQUESTS are asserted, PostgreSQL row-lock behaviour is not proven.

Fixture geometry: routing planned_blanks 10, blank 104 mm, kerf 3 mm, 10 cuts -> every blank costs 107 mm.
"""
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query

from app.core.database import Base
from app.models import *  # noqa: F401,F403
from app.models.audit import AuditLog
from app.models.rejection_type import RejectionType
from app.models.user import UserRole
from app.models.work_order import WorkOrder, WORoute
from app.models.production_movement import StageWIP
from app.schemas.continuous_casting import CCCutResultCreate
from app.schemas.operations import WOReleaseCreate
from app.schemas.production import MovePartsRequest, RecordStageProductionRequest
import app.services.continuous_casting_cut_service as cut_svc
import app.services.continuous_casting_reservation_service as rv_svc
from app.services.continuous_casting_cut_service import ContinuousCastingCutService as Cuts
from app.services.continuous_casting_gate_service import ContinuousCastingGateService as Gate
from app.services.operations_service import OperationsService
from app.services.production_service import ProductionService

from test_cc_reservation_service import (  # noqa: F401
    db, world, Ledger, Alloc, Unit, Routing, Inward,
    _user, make_wo, _material, accepted_units, new_routing, supersede, allocate, reserve, release,
    count, rows, snapshot, fresh, ledger_totals, _raising_listener, cc,
)
from test_cc_issue_service import issue  # noqa: F401
from test_cc_cut_consume_service import cut  # noqa: F401

Cut = cc.ContinuousCastingCutRecord
BLANK, KERF = 104, 3
PER_BLANK = BLANK + KERF                                       # 107 mm for one blank and its cut
OMS_TABLES = ["stage_wips", "production_updates", "production_movements", "nc_records", "audit_logs",
              "wo_routes", "work_orders", "packing_records"]


# ------------------------------------------------------------------ helpers
def oms_snapshot(db):
    return {t: rows(db, t) for t in OMS_TABLES}


def china_snapshot(db):
    return {t: rows(db, t) for t in ["cc_cut_records", "cc_stock_ledger", "cc_stock_units", "cc_allocations"]}


def build(db, wo_no="WO-1001", route=("F2", "F3", "DISPATCH"), qty=10, with_routing=True):
    """A real released WO (through OperationsService.release_work_order) with a China routing, one 2000 mm
    ACCEPTED unit and a 1070 mm allocation."""
    mat = db.query(cc.ContinuousCastingMaterial).first() or _material(db)
    if not db.query(RejectionType).filter_by(code="DEF-POROSITY").first():
        db.add(RejectionType(code="DEF-POROSITY", name="Porosity", is_active=True))
        db.commit()
    make_wo(db, wo_no)
    OperationsService.release_work_order(
        db, WOReleaseCreate(wo_number=wo_no, physical_wo_qty=qty, route_stages=list(route)), _user(db, UserRole.ADMIN))
    ctx = dict(db=db, mat=mat, wo_no=wo_no, wo=db.query(WorkOrder).filter_by(wo_number=wo_no).one())
    if with_routing:
        (unit,) = accepted_units(db, mat, [2000])
        rid = new_routing(db, mat, wo_no)
        ctx.update(unit=unit, rid=rid, alloc=allocate(db, rid, unit, 1070))
    return ctx


@pytest.fixture()
def china(db):
    return build(db)


def do_cut(ctx, length):
    db = ctx["db"]
    reserve(db, ctx["rid"], ctx["alloc"], length), issue(db, ctx["rid"], ctx["alloc"], length)
    return cut(db, ctx["rid"], ctx["alloc"], length).ledger_transaction_number


def result_req(ctx, txn, good, rej, cuts, trim=0, consumed=None, **over):
    data = dict(routing_id=ctx["rid"], allocation_id=ctx["alloc"].id, stock_unit_id=ctx["unit"].id,
                ledger_transaction_number=txn,
                consumed_length_mm=consumed if consumed is not None else (good + rej) * BLANK + cuts * KERF + trim,
                actual_good_blanks=good, rejected_blanks=rej, actual_cuts=cuts, end_trim_mm=trim)
    data.update(over)
    return CCCutResultCreate(**data)


def record(ctx, txn, good, rej, cuts, trim=0, consumed=None, user=None, **over):
    db = ctx["db"]
    return Cuts.record_cut_result(db, result_req(ctx, txn, good, rej, cuts, trim, consumed, **over),
                                  user or _user(db, UserRole.PRODUCTION_MANAGER))


def reconciled(ctx, good, rej=0):
    """A real cut of exactly the length (good+rejected) blanks need, and its RECONCILED result."""
    n = good + rej
    txn = do_cut(ctx, n * PER_BLANK)
    return record(ctx, txn, good, rej, n)


def produce(ctx, stage, good, rej=0):
    db = ctx["db"]
    return ProductionService.record_stage_production(
        db, RecordStageProductionRequest(wo_number=ctx["wo_no"], stage=stage, good_qty=good, rejected_quantity=rej,
                                         defect_code="DEF-POROSITY" if rej else None), _user(db, UserRole.PRODUCTION_MANAGER))


def move(ctx, frm, to, qty, rej=0):
    db = ctx["db"]
    return ProductionService.move_parts(
        db, MovePartsRequest(wo_number=ctx["wo_no"], from_stage=frm, to_stage=to, quantity_moved=qty,
                             rejected_quantity=rej, defect_code="DEF-POROSITY" if rej else None),
        _user(db, UserRole.PRODUCTION_MANAGER))


def wip(db, wo_no, stage):
    w = db.query(WorkOrder).filter_by(wo_number=wo_no).one()
    return db.query(StageWIP).filter_by(work_order_id=w.id, stage=stage).one()


def rejected_by_gate(call, fragment="material gate"):
    with pytest.raises(HTTPException) as e:
        call()
    assert e.value.status_code == 400 and fragment in e.value.detail, e.value.detail
    return e.value.detail


# ================================================================== CUT RESULT
def test_a_valid_cut_result_reconciles_exactly(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)                                   # 535 mm consumed
    ledger_before = rows(db, "cc_stock_ledger")
    units_before = rows(db, "cc_stock_units")
    allocs_before = rows(db, "cc_allocations")
    pm = _user(db, UserRole.PRODUCTION_MANAGER)
    r = record(china, txn, good=4, rej=1, cuts=5, user=pm, remarks="saw 2")
    assert r.success and not r.replayed and r.reconciliation_status == "RECONCILED" and r.variance_mm == 0
    assert (r.required_length_mm, r.consumed_length_mm, r.usable_for_oms) == (535, 535, True)
    assert (r.actual_good_blanks, r.rejected_blanks, r.actual_cuts, r.end_trim_mm) == (4, 1, 5, 0)
    assert (r.blank_length_mm, r.kerf_mm, r.planned_blanks) == (BLANK, KERF, 10)           # from the routing
    assert (r.routing_blanks_recorded, r.routing_planned_blanks) == (5, 10) and r.wo_number == "WO-1001"
    row = db.query(Cut).one()
    assert row.cut_number == r.cut_number and row.reconciliation_status == "RECONCILED" and row.variance_mm == 0
    assert row.work_order_id == china["wo"].id and row.allocation_id == china["alloc"].id
    assert row.stock_unit_id == china["unit"].id
    assert row.ledger_entry_id == db.query(Ledger).filter_by(transaction_number=txn).one().id
    assert (row.planned_blanks, row.actual_good_blanks, row.rejected_blanks, row.blank_length_mm, row.kerf_mm,
            row.actual_cuts, row.end_trim_mm, row.consumed_length_mm) == (10, 4, 1, 104, 3, 5, 0, 535)
    assert row.performed_by_id == pm.id and row.remarks == "saw 2" and row.client_request_id is None
    assert row.retained_remnant_unit_id is None and row.retained_remnant_length_mm == 0        # untouched
    assert db.query(AuditLog).filter(AuditLog.action == "CC_CUT_RESULT").count() == 1
    assert rows(db, "cc_stock_ledger") == ledger_before                  # no ledger row created or changed
    assert rows(db, "cc_stock_units") == units_before and rows(db, "cc_allocations") == allocs_before
    assert db.query(Ledger).filter_by(movement_type="CUT_CONSUME").count() == 1


def test_end_trim_and_kerf_are_part_of_the_required_length(china):
    txn = do_cut(china, 3 * BLANK + 3 * KERF + 20)                       # 3 blanks, 3 cuts, 20 mm trim = 341
    r = record(china, txn, 3, 0, 3, trim=20)
    assert (r.required_length_mm, r.reconciliation_status, r.variance_mm) == (341, "RECONCILED", 0)


def test_unexplained_consumption_is_a_variance_and_is_not_usable(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK + 5)                               # 5 mm more than 5 blanks need
    r = record(china, txn, 5, 0, 5, consumed=5 * PER_BLANK + 5)
    assert (r.reconciliation_status, r.variance_mm, r.required_length_mm, r.usable_for_oms) == ("VARIANCE", 5, 535, False)
    assert "NOT usable" in r.message and db.query(Cut).one().variance_mm == 5
    assert Gate.usable_good_blanks(db, china["wo"], db.query(Routing).one()) == 0


def test_consumed_length_too_short_for_the_blanks_is_rejected(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK - 1)                                # 1 mm short of what 5 blanks need
    before = china_snapshot(db)
    with pytest.raises(HTTPException) as e:
        record(china, txn, 5, 0, 5, consumed=534)
    assert e.value.status_code == 400 and "needs 535 mm" in e.value.detail
    assert china_snapshot(db) == before and db.query(Cut).count() == 0
    r = record(china, txn, 4, 0, 4, consumed=534)                          # fewer blanks fit: 428 needed, 106 unexplained
    assert (r.reconciliation_status, r.variance_mm, r.required_length_mm) == ("VARIANCE", 106, 428)


def test_a_cut_result_needs_a_real_cut_consume_transaction(china):
    db = china["db"]
    do_cut(china, 5 * PER_BLANK)
    issue_txn = db.query(Ledger).filter_by(movement_type="ISSUE").first().transaction_number
    before = china_snapshot(db)
    for bogus, fragment in (("TXN-999999", "does not exist"), (issue_txn, "not a CUT_CONSUME")):
        with pytest.raises(HTTPException) as e:
            record(china, bogus, 5, 0, 5)
        assert e.value.status_code == 400 and fragment in e.value.detail
    assert china_snapshot(db) == before


def test_the_ledger_routing_allocation_and_unit_must_agree(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    # a second WO with its own routing / unit / allocation and its own real cut
    other = build(db, "WO-1002")
    other_txn = do_cut(other, 2 * PER_BLANK)
    before = china_snapshot(db)

    def attempt(**over):
        with pytest.raises(HTTPException) as e:
            record(china, over.pop("txn", txn), 5, 0, 5, **over)
        assert e.value.status_code in (400, 404), e.value.detail
        return e.value.detail

    attempt(routing_id=other["rid"])                                      # wrong routing for this allocation
    attempt(allocation_id=other["alloc"].id)                              # wrong allocation (other routing too)
    attempt(stock_unit_id=other["unit"].id)                               # wrong stock unit
    assert "was not a cut of allocation" in attempt(txn=other_txn)        # another allocation's cut transaction
    assert attempt(allocation_id=uuid.uuid4()) == "Allocation not found."
    assert china_snapshot(db) == before


def test_consumed_length_must_equal_the_ledger_row(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    before = china_snapshot(db)
    for wrong in (534, 536, 1):
        with pytest.raises(HTTPException) as e:
            record(china, txn, 5, 0, 5, consumed=wrong)
        assert e.value.status_code == 400 and "does not match the 535 mm consumed" in e.value.detail
    assert china_snapshot(db) == before


@pytest.mark.parametrize("field", ["actual_good_blanks", "rejected_blanks", "actual_cuts", "end_trim_mm",
                                   "consumed_length_mm"])
def test_negative_and_non_integer_values_are_rejected(china, field):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    base = dict(routing_id=china["rid"], allocation_id=china["alloc"].id, stock_unit_id=china["unit"].id,
                ledger_transaction_number=txn, consumed_length_mm=535, actual_good_blanks=4, rejected_blanks=1,
                actual_cuts=5, end_trim_mm=0)
    for bad in (-1, 1.5, None):
        with pytest.raises(ValidationError):
            CCCutResultCreate(**{**base, field: bad})
    raw = CCCutResultCreate.model_construct(**{**base, field: -1}, remarks=None, client_request_id=None)
    before = china_snapshot(db)
    with pytest.raises(HTTPException) as e:
        Cuts.record_cut_result(db, raw, _user(db, UserRole.PRODUCTION_MANAGER))
    assert e.value.status_code == 400 and china_snapshot(db) == before


def test_a_cut_result_needs_at_least_one_blank(china):
    txn = do_cut(china, 107)
    with pytest.raises(HTTPException) as e:
        record(china, txn, 0, 0, 1, consumed=107)
    assert e.value.status_code == 400 and "at least one" in e.value.detail


def test_blank_length_kerf_and_cumulative_figures_cannot_be_supplied(china):
    txn = do_cut(china, 5 * PER_BLANK)
    for extra in ({"blank_length_mm": 104}, {"kerf_mm": 3}, {"routing_blanks_recorded": 0},
                  {"planned_blanks": 99}, {"usable_good_blanks": 99}, {"reconciliation_status": "RECONCILED"},
                  {"variance_mm": 0}):
        with pytest.raises(ValidationError):
            result_req(china, txn, 4, 1, 5, **extra)


def test_a_recorded_cut_result_is_immutable(china):
    db = china["db"]
    reconciled(china, 4, 1)
    row = db.query(Cut).one()
    row.actual_good_blanks = 99
    with pytest.raises(ValueError):
        db.flush()
    db.rollback()
    row = db.query(Cut).one()
    db.delete(row)
    with pytest.raises(ValueError):
        db.flush()
    db.rollback()
    assert db.query(Cut).one().actual_good_blanks == 4


def test_only_one_result_per_cut_consume_row(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    record(china, txn, 4, 1, 5)
    before = china_snapshot(db)
    for good, rej in ((4, 1), (5, 0)):
        with pytest.raises(HTTPException) as e:
            record(china, txn, good, rej, 5)
        assert e.value.status_code == 409 and "immutable" in e.value.detail
    assert china_snapshot(db) == before and db.query(Cut).count() == 1
    db.add(Cut(cut_number="CUT-DUP", work_order_id=china["wo"].id, allocation_id=china["alloc"].id,
               stock_unit_id=china["unit"].id, ledger_entry_id=db.query(Cut).one().ledger_entry_id,
               blank_length_mm=BLANK))
    with pytest.raises(IntegrityError):                                    # and the database says so too
        db.flush()
    db.rollback()


def test_idempotent_replay_and_key_reuse(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    first = record(china, txn, 4, 1, 5, client_request_id="CUT-REQ-1")
    n, rows_before = db.query(Cut).count(), china_snapshot(db)
    again = record(china, txn, 4, 1, 5, client_request_id="CUT-REQ-1")
    assert again.replayed and not first.replayed and again.cut_number == first.cut_number
    assert db.query(Cut).count() == n and china_snapshot(db) == rows_before
    for call in (lambda: record(china, txn, 5, 0, 5, client_request_id="CUT-REQ-1"),           # other blanks
                 lambda: record(china, txn, 4, 1, 5, trim=3, consumed=538, client_request_id="CUT-REQ-1")):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 409 and "different request" in e.value.detail
    other = do_cut(china, 2 * PER_BLANK)
    with pytest.raises(HTTPException) as e:                                 # same key, different transaction
        record(china, other, 2, 0, 2, client_request_id="CUT-REQ-1")
    assert e.value.status_code == 409
    assert record(china, other, 2, 0, 2).cut_number != first.cut_number     # no key: independent
    assert db.query(Cut).count() == 2


@pytest.mark.parametrize("blank_counts", [(3, 3), (5, 1), (2, 4)])
def test_blanks_recorded_across_the_routing_cannot_pass_the_planned_blanks(china, blank_counts):
    db = china["db"]
    db.execute(Base.metadata.tables["cc_routings"].update().values(planned_blanks=5))   # a routing planned for 5 blanks
    db.commit()
    first, second = blank_counts
    record(china, do_cut(china, first * PER_BLANK), first, 0, first)
    txn = do_cut(china, second * PER_BLANK)
    before = china_snapshot(db)
    with pytest.raises(HTTPException) as e:
        record(china, txn, second, 0, second)
    assert e.value.status_code == 400 and "planned blank" in e.value.detail and china_snapshot(db) == before
    room = 5 - first                                                        # what the routing still has room for
    if room:
        small = do_cut(china, room * PER_BLANK)
        assert record(china, small, room, 0, room).routing_blanks_recorded == 5


@pytest.mark.parametrize("role,allowed", [(UserRole.ADMIN, True), (UserRole.PRODUCTION_MANAGER, True),
                                          (UserRole.PLANNER, False), (UserRole.STORE, False), (UserRole.QA, False),
                                          (UserRole.ENGINEERING, False), (UserRole.CEO, False),
                                          (UserRole.MACHINE_OPERATOR, False)])
def test_cut_result_roles(china, role, allowed):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    who = _user(db, role)
    before = china_snapshot(db)
    if allowed:
        assert record(china, txn, 5, 0, 5, user=who).success
    else:
        with pytest.raises(HTTPException) as e:
            record(china, txn, 5, 0, 5, user=who)
        assert e.value.status_code == 403 and china_snapshot(db) == before


def test_anonymous_cannot_record_a_cut_result(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    with pytest.raises(HTTPException) as e:
        Cuts.record_cut_result(db, result_req(china, txn, 5, 0, 5), None)
    assert e.value.status_code == 403


def test_a_superseded_routings_cut_can_be_recorded_but_is_not_usable(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    supersede(db, china["mat"])
    r = record(china, txn, 5, 0, 5)
    assert (r.routing_status, r.reconciliation_status, r.usable_for_oms) == ("SUPERSEDED", "RECONCILED", False)


def test_a_draft_routing_cannot_have_a_cut_result(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    db.query(Routing).one().status = "DRAFT"
    db.commit()
    with pytest.raises(HTTPException) as e:
        record(china, txn, 5, 0, 5)
    assert e.value.status_code == 400 and "DRAFT" in e.value.detail


def test_cut_result_rolls_back_atomically(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    before = china_snapshot(db)
    for model in (Cut, AuditLog):
        off = _raising_listener(model, "before_insert")
        try:
            with pytest.raises(RuntimeError):
                record(china, txn, 5, 0, 5)
        finally:
            off()
        assert china_snapshot(db) == before and db.query(AuditLog).filter_by(action="CC_CUT_RESULT").count() == 0
    assert record(china, txn, 5, 0, 5).success


def test_cut_result_commit_failure_rolls_back(china, monkeypatch):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK)
    req = result_req(china, txn, 5, 0, 5)
    pm = _user(db, UserRole.PRODUCTION_MANAGER)
    before = china_snapshot(db)

    def failing():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", failing)
    with pytest.raises(RuntimeError):
        Cuts.record_cut_result(db, req, pm)
    monkeypatch.undo()
    assert china_snapshot(db) == before


def test_cut_number_collision_is_retried_then_a_controlled_409(china, monkeypatch):
    db = china["db"]
    first = reconciled(china, 2)
    taken, real, calls = first.cut_number, cut_svc.next_cc_cut_number, []
    txn = do_cut(china, 3 * PER_BLANK)

    def flaky(session):
        calls.append(1)
        return taken if len(calls) == 1 else real(session)

    monkeypatch.setattr(cut_svc, "next_cc_cut_number", flaky)
    assert record(china, txn, 3, 0, 3).cut_number != taken and len(calls) == 2
    other = do_cut(china, 2 * PER_BLANK)
    monkeypatch.setattr(cut_svc, "next_cc_cut_number", lambda session: taken)
    before = china_snapshot(db)
    with pytest.raises(HTTPException) as e:
        record(china, other, 2, 0, 2)
    assert e.value.status_code == 409 and china_snapshot(db) == before


def test_cut_result_lock_order_is_unit_allocation_routing(china, monkeypatch):
    txn = do_cut(china, 5 * PER_BLANK)
    order, real = [], Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    record(china, txn, 5, 0, 5)
    assert order == [Unit, Alloc, Routing]


def test_cut_result_database_constraints(china):
    db = china["db"]
    txn = do_cut(china, 107)
    ledger_id = db.query(Ledger).filter_by(transaction_number=txn).one().id

    def row(n, **kw):
        d = dict(cut_number=n, work_order_id=china["wo"].id, allocation_id=china["alloc"].id,
                 stock_unit_id=china["unit"].id, blank_length_mm=BLANK)
        d.update(kw)
        return Cut(**d)

    for bad in (row("CUT-B1", reconciliation_status="RECONCILED", variance_mm=5),
                row("CUT-B2", reconciliation_status="RECONCILED", variance_mm=None),
                row("CUT-B3", reconciliation_status="VARIANCE", variance_mm=0),
                row("CUT-B4", reconciliation_status="VARIANCE", variance_mm=None),
                row("CUT-B5", actual_cuts=-1)):
        db.add(bad)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    db.add(row("CUT-OK", reconciliation_status="RECONCILED", variance_mm=0, ledger_entry_id=ledger_id,
               client_request_id="K-1"))
    db.flush()
    db.add(row("CUT-K2", client_request_id="K-1"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ================================================================== THE GATE
def test_a_wo_without_a_china_routing_is_completely_unchanged(db):
    ctx = build(db, "WO-2001", route=("F1", "F2", "DISPATCH"), with_routing=False)
    r = produce(ctx, "F1", 6, 2)
    assert r.success and wip(db, "WO-2001", "F1").ok_qty == 6
    assert move(ctx, "F1", "F2", 4).success
    assert Gate.active_china_routing(db, ctx["wo"]) is None


def test_an_f1_production_routing_is_completely_unchanged(db):
    ctx = build(db, "WO-2002", route=("F1", "F2", "DISPATCH"), with_routing=False)
    db.add(Routing(work_order_id=ctx["wo"].id, version=1, material_source="F1_PRODUCTION", status="ACTIVE"))
    db.commit()
    assert Gate.active_china_routing(db, ctx["wo"]) is None
    assert produce(ctx, "F1", 10).success
    assert move(ctx, "F1", "F2", 10).success


def test_china_routing_without_a_cut_result_blocks_first_stage_production(china):
    db = china["db"]
    do_cut(china, 5 * PER_BLANK)                                          # material consumed, but no cut RESULT
    before_oms, before_china = oms_snapshot(db), china_snapshot(db)
    detail = rejected_by_gate(lambda: produce(china, "F2", 1))
    assert "0 usable good blank" in detail
    assert oms_snapshot(db) == before_oms and china_snapshot(db) == before_china        # nothing mutated


def test_an_unreconciled_cut_result_is_not_usable(china):
    db = china["db"]
    txn = do_cut(china, 5 * PER_BLANK + 1)
    assert record(china, txn, 5, 0, 5, consumed=5 * PER_BLANK + 1).reconciliation_status == "VARIANCE"
    before = oms_snapshot(db)
    rejected_by_gate(lambda: produce(china, "F2", 1))
    assert oms_snapshot(db) == before


def test_a_reconciled_cut_result_allows_production_up_to_its_good_blanks(china):
    db = china["db"]
    reconciled(china, good=4, rej=1)                                      # 4 usable good blanks
    r = produce(china, "F2", 4)
    assert r.success and (r.stage_ok_total, r.stage_rejection_total) == (4, 0)
    assert wip(db, "WO-1001", "F2").ok_qty == 4
    before = oms_snapshot(db)
    rejected_by_gate(lambda: produce(china, "F2", 1))                      # one over the limit
    assert oms_snapshot(db) == before


def test_good_plus_rejected_cannot_exceed_the_usable_good_blanks(china):
    db = china["db"]
    reconciled(china, 4, 1)
    before = oms_snapshot(db)
    rejected_by_gate(lambda: produce(china, "F2", 3, 2))                   # 5 > 4: rejected pieces count too
    assert oms_snapshot(db) == before
    assert produce(china, "F2", 2, 2).success                              # exactly at the limit: 2 good + 2 rejected
    rejected_by_gate(lambda: produce(china, "F2", 0, 1))                   # even one rejected piece is one over
    w = wip(db, "WO-1001", "F2")
    assert (w.ok_qty, w.rejected_qty) == (2, 2)


@pytest.mark.parametrize("steps", [(1, 1, 1, 1), (2, 2), (3, 1), (4,)])
def test_partial_production_works_up_to_the_boundary(china, steps):
    db = china["db"]
    reconciled(china, 4, 1)
    for good in steps:
        assert produce(china, "F2", good).success
    assert wip(db, "WO-1001", "F2").ok_qty == 4
    rejected_by_gate(lambda: produce(china, "F2", 1))


def test_usable_blanks_accumulate_across_reconciled_cut_results(china):
    db = china["db"]
    reconciled(china, 2)
    assert produce(china, "F2", 2).success
    rejected_by_gate(lambda: produce(china, "F2", 1))
    reconciled(china, 3, 1)                                               # a second real cut adds 3 usable blanks
    assert Gate.usable_good_blanks(db, china["wo"], db.query(Routing).one()) == 5
    assert produce(china, "F2", 3).success
    rejected_by_gate(lambda: produce(china, "F2", 1))
    assert wip(db, "WO-1001", "F2").ok_qty == 5


def test_rejected_blanks_never_become_usable_good_pieces(china):
    db = china["db"]
    reconciled(china, good=1, rej=4)
    assert Gate.usable_good_blanks(db, china["wo"], db.query(Routing).one()) == 1
    assert produce(china, "F2", 1).success
    rejected_by_gate(lambda: produce(china, "F2", 1))


def test_move_parts_out_of_the_first_stage_is_gated(china):
    db = china["db"]
    reconciled(china, 4, 1)
    before = oms_snapshot(db)
    rejected_by_gate(lambda: move(china, "F2", "F3", 5))                   # direct production of 5 > 4
    assert oms_snapshot(db) == before
    rejected_by_gate(lambda: move(china, "F2", "F3", 3, 2))                # 3 moved + 2 rejected = 5 > 4
    assert oms_snapshot(db) == before
    assert move(china, "F2", "F3", 3, 1).success                           # exactly 4 pieces
    assert (wip(db, "WO-1001", "F2").ok_qty, wip(db, "WO-1001", "F2").rejected_qty) == (3, 1)
    rejected_by_gate(lambda: move(china, "F2", "F3", 1))                   # one over


def test_move_parts_without_any_cut_result_is_blocked(china):
    db = china["db"]
    before = oms_snapshot(db)
    rejected_by_gate(lambda: move(china, "F2", "F3", 1))
    assert oms_snapshot(db) == before


def test_moving_already_produced_pieces_adds_no_new_production(china):
    db = china["db"]
    reconciled(china, 4, 1)
    assert produce(china, "F2", 4).success                                 # production entry: 4 good, on hand
    assert move(china, "F2", "F3", 4).success                              # additional_ok = 0: not new production
    assert wip(db, "WO-1001", "F2").ok_qty == 4 and wip(db, "WO-1001", "F3").ent_qty == 4


def test_pieces_produced_before_the_routing_became_active_can_still_be_moved(db):
    """existing first-stage production (4) already exceeds the usable blanks (0) when a China routing becomes
    ACTIVE; moving those already-produced pieces creates NO new production, so it must stay allowed, while
    any new piece is still gated."""
    ctx = build(db, "WO-8001", with_routing=False)
    assert produce(ctx, "F2", 4).success                                   # ordinary OMS production, no routing yet
    (unit,) = accepted_units(db, ctx["mat"], [2000])
    rid = new_routing(db, ctx["mat"], "WO-8001")                           # the China routing becomes ACTIVE now
    ctx.update(unit=unit, rid=rid, alloc=allocate(db, rid, unit, 1070))
    assert Gate.usable_good_blanks(db, ctx["wo"], Gate.active_china_routing(db, ctx["wo"])) == 0
    assert move(ctx, "F2", "F3", 4).success                                # additional = 0: allowed
    assert wip(db, "WO-8001", "F3").ent_qty == 4
    rejected_by_gate(lambda: produce(ctx, "F2", 1))                        # new production is gated


def test_the_gate_only_applies_to_the_first_stage(china):
    db = china["db"]
    reconciled(china, 4, 1)
    assert produce(china, "F2", 4).success and move(china, "F2", "F3", 4).success
    assert produce(china, "F3", 4).success                                 # F3 is downstream: not the China gate's business
    assert move(china, "F3", "DISPATCH", 4).success


def test_f1_as_the_first_route_stage_is_rejected_for_an_active_china_routing(db):
    ctx = build(db, "WO-3001", route=("F1", "F2", "DISPATCH"))
    reconciled(ctx, 4, 1)                                                  # even with usable blanks
    before = oms_snapshot(db)
    detail = rejected_by_gate(lambda: produce(ctx, "F1", 1), "bypasses F1")
    assert "cannot produce at F1" in detail
    rejected_by_gate(lambda: move(ctx, "F1", "F2", 1), "bypasses F1")
    assert oms_snapshot(db) == before and db.query(StageWIP).filter_by(stage="F1").one().ok_qty == 0
    with pytest.raises(HTTPException) as e:                               # the second stage is outside the China gate
        produce(ctx, "F2", 1)
    assert "material gate" not in e.value.detail and "bypasses F1" not in e.value.detail


@pytest.mark.parametrize("status_value", ["SUPERSEDED", "DRAFT"])
def test_a_superseded_or_draft_routing_does_not_gate(china, status_value):
    db = china["db"]
    db.query(Routing).one().status = status_value
    db.commit()
    assert Gate.active_china_routing(db, china["wo"]) is None
    assert produce(china, "F2", 10).success                               # unchanged OMS behaviour (no gate)


def test_after_a_supersession_only_the_new_active_routings_cut_results_count(china):
    db = china["db"]
    reconciled(china, 4, 1)                                                # cut results of routing v1
    new_rid = supersede(db, china["mat"])                                  # v2 becomes the ACTIVE routing
    before = oms_snapshot(db)
    rejected_by_gate(lambda: produce(china, "F2", 1))                      # v1's blanks are not v2's
    assert oms_snapshot(db) == before
    (u2,) = accepted_units(db, china["mat"], [2000])
    new = dict(china, rid=new_rid, unit=u2, alloc=allocate(db, new_rid, u2, 1070))
    reconciled(new, 2)
    assert produce(china, "F2", 2).success
    rejected_by_gate(lambda: produce(china, "F2", 1))


def test_another_work_orders_cut_result_cannot_contribute(db):
    a = build(db, "WO-4001")
    b = build(db, "WO-4002")
    reconciled(b, 5)                                                       # plenty of blanks, for the OTHER WO
    before = oms_snapshot(db)
    rejected_by_gate(lambda: produce(a, "F2", 1))
    assert oms_snapshot(db) == before
    assert produce(b, "F2", 5).success


@pytest.mark.parametrize("flaw", ["not_a_cut_consume", "consumed_mismatch", "allocation_mismatch", "unit_mismatch",
                                  "other_routing_allocation", "variance"])
def test_forged_or_inconsistent_cut_records_are_never_counted(db, flaw):
    """The gate re-verifies every record against its CUT_CONSUME ledger row, allocation and routing."""
    ctx = build(db, "WO-6001")
    other = build(db, "WO-6002")
    txn = do_cut(ctx, 5 * PER_BLANK)
    ledger = db.query(Ledger).filter_by(transaction_number=txn).one()
    inward_row = db.query(Ledger).filter_by(movement_type="INWARD", stock_unit_id=ctx["unit"].id).one()
    spec = dict(cut_number="CUT-FORGED", work_order_id=ctx["wo"].id, allocation_id=ctx["alloc"].id,
                stock_unit_id=ctx["unit"].id, ledger_entry_id=ledger.id, planned_blanks=10, actual_good_blanks=5,
                rejected_blanks=0, blank_length_mm=BLANK, kerf_mm=KERF, actual_cuts=5, consumed_length_mm=535,
                reconciliation_status="RECONCILED", variance_mm=0)
    if flaw == "not_a_cut_consume":
        spec.update(ledger_entry_id=inward_row.id, consumed_length_mm=inward_row.length_mm)
    elif flaw == "consumed_mismatch":
        spec.update(consumed_length_mm=536)
    elif flaw == "allocation_mismatch":
        spec.update(allocation_id=other["alloc"].id)
    elif flaw == "unit_mismatch":
        spec.update(stock_unit_id=other["unit"].id)
    elif flaw == "other_routing_allocation":
        spec.update(allocation_id=other["alloc"].id, stock_unit_id=other["unit"].id)
    else:
        spec.update(reconciliation_status="VARIANCE", variance_mm=5)
    db.add(Cut(**spec))
    db.commit()
    assert Gate.usable_good_blanks(db, ctx["wo"], db.query(Routing).filter_by(work_order_id=ctx["wo"].id).one()) == 0
    before = oms_snapshot(db)
    rejected_by_gate(lambda: produce(ctx, "F2", 1))
    assert oms_snapshot(db) == before


def _forged(ctx, ledger_row, **over):
    """A cut record that is perfect except for what `over` breaks (one condition at a time)."""
    spec = dict(cut_number="CUT-" + uuid.uuid4().hex[:8].upper(), work_order_id=ctx["wo"].id,
                allocation_id=ctx["alloc"].id, stock_unit_id=ctx["unit"].id, ledger_entry_id=ledger_row.id,
                planned_blanks=10, actual_good_blanks=ledger_row.length_mm // PER_BLANK, rejected_blanks=0,
                blank_length_mm=BLANK, kerf_mm=KERF, actual_cuts=ledger_row.length_mm // PER_BLANK,
                consumed_length_mm=ledger_row.length_mm, reconciliation_status="RECONCILED", variance_mm=0)
    spec.update(over)
    return Cut(**spec)


def test_the_forging_helper_itself_would_be_counted_if_it_were_perfect(db):
    """Control: a hand-built record with every condition satisfied IS counted -- so each isolation test below
    proves its single broken condition is what keeps the record out."""
    ctx = build(db, "WO-7000")
    do_cut(ctx, 5 * PER_BLANK)
    row = db.query(Ledger).filter_by(movement_type="CUT_CONSUME", stock_unit_id=ctx["unit"].id).one()
    db.add(_forged(ctx, row))
    db.commit()
    assert Gate.usable_good_blanks(db, ctx["wo"], db.query(Routing).one()) == 5


def test_a_pending_cut_record_is_not_counted_even_with_zero_variance(db):
    ctx = build(db, "WO-7001")
    do_cut(ctx, 5 * PER_BLANK)
    row = db.query(Ledger).filter_by(movement_type="CUT_CONSUME").one()
    db.add(_forged(ctx, row, reconciliation_status="PENDING", variance_mm=0))      # allowed by the CHECK
    db.commit()
    assert Gate.usable_good_blanks(db, ctx["wo"], db.query(Routing).one()) == 0
    rejected_by_gate(lambda: produce(ctx, "F2", 1))


def test_a_record_pointing_at_a_non_cut_consume_row_is_not_counted(db):
    """The ISSUE row has the same allocation, unit and length as the cut: only its movement type is wrong."""
    ctx = build(db, "WO-7002")
    do_cut(ctx, 5 * PER_BLANK)
    issue_row = db.query(Ledger).filter_by(movement_type="ISSUE").one()
    assert (issue_row.allocation_id, issue_row.stock_unit_id, issue_row.length_mm) == (
        ctx["alloc"].id, ctx["unit"].id, 535)
    db.add(_forged(ctx, issue_row))
    db.commit()
    assert Gate.usable_good_blanks(db, ctx["wo"], db.query(Routing).one()) == 0


def test_a_record_naming_the_wrong_work_order_is_not_counted(db):
    a = build(db, "WO-7003")
    b = build(db, "WO-7004")
    do_cut(a, 5 * PER_BLANK)
    row = db.query(Ledger).filter_by(movement_type="CUT_CONSUME", allocation_id=a["alloc"].id).one()
    db.add(_forged(a, row, work_order_id=b["wo"].id))          # a's allocation and cut, but filed under b's WO
    db.commit()
    routing_a = db.query(Routing).filter_by(work_order_id=a["wo"].id).one()
    routing_b = db.query(Routing).filter_by(work_order_id=b["wo"].id).one()
    assert Gate.usable_good_blanks(db, a["wo"], routing_a) == 0     # a: the record names another WO
    assert Gate.usable_good_blanks(db, b["wo"], routing_b) == 0     # b: its allocation is not in b's routing


def test_a_record_whose_allocation_differs_from_the_ledger_rows_is_not_counted(db):
    """Two WOs share one physical unit. The cut was made through WO-B's allocation; a record that claims it for
    WO-A's allocation (same unit, same length, real CUT_CONSUME row, same routing as A) breaks only that match."""
    mat = _material(db)
    a = build(db, "WO-7005", with_routing=False)
    b = build(db, "WO-7006", with_routing=False)
    (shared_unit,) = accepted_units(db, mat, [2000])
    rid_a, rid_b = new_routing(db, mat, "WO-7005"), new_routing(db, mat, "WO-7006")
    a.update(unit=shared_unit, rid=rid_a, alloc=allocate(db, rid_a, shared_unit, 500))
    b.update(unit=shared_unit, rid=rid_b, alloc=allocate(db, rid_b, shared_unit, 500))
    do_cut(b, 2 * PER_BLANK)                                        # WO-B's own cut of 214 mm
    row = db.query(Ledger).filter_by(movement_type="CUT_CONSUME").one()
    assert row.allocation_id == b["alloc"].id and row.stock_unit_id == shared_unit.id
    db.add(_forged(a, row))                                         # claimed for WO-A's allocation
    db.commit()
    routing_a = db.query(Routing).filter_by(work_order_id=a["wo"].id).one()
    assert Gate.usable_good_blanks(db, a["wo"], routing_a) == 0
    rejected_by_gate(lambda: produce(a, "F2", 1))


def test_planned_reserved_issued_and_consumed_quantities_cannot_bypass_the_gate(china):
    db = china["db"]
    # planned 10 blanks, 1070 mm allocated, 535 reserved, issued and CONSUMED -- but no recorded cut result
    do_cut(china, 5 * PER_BLANK)
    reserve(db, china["rid"], china["alloc"], 100)
    a = fresh(db, Alloc, china["alloc"].id)
    assert (a.planned_length_mm, a.reserved_length_mm, a.consumed_length_mm) == (1070, 100, 535)
    assert db.query(Routing).one().planned_blanks == 10
    before = oms_snapshot(db)
    rejected_by_gate(lambda: produce(china, "F2", 1))
    rejected_by_gate(lambda: move(china, "F2", "F3", 1))
    assert oms_snapshot(db) == before


def test_a_client_supplied_cumulative_value_cannot_bypass_the_gate(china):
    db = china["db"]
    reconciled(china, 2)
    req = RecordStageProductionRequest(
        wo_number="WO-1001", stage="F2", good_qty=3, rejected_quantity=0, **{})   # the schema has no cumulative field
    payload = req.model_dump()
    payload.update(cumulative_good=999, usable_good_blanks=999, available_blanks=999)   # ignored extras
    forged = RecordStageProductionRequest(**payload)
    before = oms_snapshot(db)
    rejected_by_gate(lambda: ProductionService.record_stage_production(db, forged, _user(db, UserRole.PRODUCTION_MANAGER)))
    assert oms_snapshot(db) == before and not hasattr(forged, "usable_good_blanks")


def test_a_rejected_request_leaves_every_oms_table_unchanged(china):
    db = china["db"]
    reconciled(china, 3)
    assert produce(china, "F2", 3).success
    before_oms, before_china = oms_snapshot(db), china_snapshot(db)
    for call in (lambda: produce(china, "F2", 1), lambda: produce(china, "F2", 0, 1),
                 lambda: move(china, "F2", "F3", 1, 1), lambda: move(china, "F2", "F3", 2, 1)):   # each adds new pieces
        rejected_by_gate(call)
        assert oms_snapshot(db) == before_oms            # StageWIP, ProductionUpdate, NC, audit, movements, WORoute
    assert china_snapshot(db) == before_china            # and the gate wrote nothing to China either


def test_the_gate_takes_no_china_locks_and_writes_nothing(china, monkeypatch):
    db = china["db"]
    reconciled(china, 4, 1)
    seen, real = [], Query.with_for_update

    def spy(self, *a, **k):
        seen.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    before = china_snapshot(db)
    assert produce(china, "F2", 2).success
    assert set(seen) <= {WorkOrder, StageWIP}                              # WO -> StageWIP only; China rows are read-only
    assert china_snapshot(db) == before


def test_the_gate_runs_after_the_release_chain_and_the_closed_wo_checks(china):
    db = china["db"]
    reconciled(china, 4, 1)
    china["wo"].engineering_released_at = None
    china["wo"].is_replacement = True                                       # replacement WOs always need the full chain
    db.commit()
    with pytest.raises(HTTPException) as e:
        produce(china, "F2", 1)
    assert "Engineering Release" in e.value.detail and "material gate" not in e.value.detail


def test_released_routes_and_wip_are_untouched_by_china_operations(china):
    db = china["db"]
    routes_before = rows(db, "wo_routes")
    wip_before = rows(db, "stage_wips")
    reconciled(china, 4, 1)
    assert rows(db, "wo_routes") == routes_before and rows(db, "stage_wips") == wip_before
    assert [r.stage for r in db.query(WORoute).order_by(WORoute.sequence)] == ["F2", "F3", "DISPATCH"]    # no dummy F1
    assert db.query(StageWIP).filter_by(stage="F1").count() == 0


def test_no_f1_record_is_required_or_created_for_a_china_wo(china):
    db = china["db"]
    reconciled(china, 4, 1)
    produce(china, "F2", 4), move(china, "F2", "F3", 4)
    assert db.query(StageWIP).filter_by(stage="F1").count() == 0
    from app.models.production import ProductionUpdate
    assert db.query(ProductionUpdate).filter_by(stage="F1").count() == 0
