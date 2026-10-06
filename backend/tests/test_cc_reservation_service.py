"""Continuous Casting RESERVE / RELEASE (Phase 4). In-memory SQLite only; the app's configured
database is never opened and no file is created.

SQLite limitation, stated plainly: SQLite ignores FOR UPDATE and serialises writers differently
from PostgreSQL, so these tests do NOT prove PostgreSQL row-lock behaviour. They prove (a) the
lock request is issued, in the fixed StockUnit -> Allocation -> Routing order, (b) balances are
re-read after the lock (stale-session scenarios on two real connections), and (c) the
transactional and CHECK-constraint invariants hold.
"""
import re
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import *  # noqa: F401,F403  (registers every table)
from app.models import continuous_casting as cc
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.production_movement import StageWIP
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.schemas.continuous_casting import (
    CCAllocationCreate, CCInwardCreate, CCReleaseCreate, CCReserveCreate, CCRoutingCreate,
    CCRoutingReleaseCreate, CCRoutingSupersede,
)
import app.services.continuous_casting_reservation_service as rv_svc
from app.services.continuous_casting_reservation_service import ContinuousCastingReservationService as Rsv
from app.services.continuous_casting_routing_service import (
    ContinuousCastingAllocationService as AllocSvc, ContinuousCastingRoutingService as RouteSvc,
)
from app.services.continuous_casting_service import ContinuousCastingInwardService as InwardSvc

OMS_TABLES = ["work_orders", "wo_routes", "stage_wips", "orders", "production_movements",
              "production_updates", "nc_records", "packing_records", "dispatches", "conversions"]
Ledger, Alloc, Unit, Routing, Inward = (cc.ContinuousCastingStockLedger, cc.ContinuousCastingAllocation,
                                        cc.ContinuousCastingStockUnit, cc.ContinuousCastingRouting,
                                        cc.ContinuousCastingInward)


# ------------------------------------------------------------------ fixtures / helpers
def _engine_session(url=None):
    engine = create_engine(url or "sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    return engine, sessionmaker(autocommit=False, autoflush=False, bind=engine)()


@pytest.fixture()
def db():
    engine, session = _engine_session()
    assert engine.url.database == ":memory:"
    Base.metadata.create_all(bind=engine)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def shared():
    """Two independent connections to ONE shared in-memory database (no file on disk)."""
    url = f"sqlite:///file:ccp4_{uuid.uuid4().hex}?mode=memory&cache=shared&uri=true"
    e1, s1 = _engine_session(url)
    e2, s2 = _engine_session(url)
    Base.metadata.create_all(bind=e1)
    yield s1, s2
    s1.close(); s2.close(); e1.dispose(); e2.dispose()


def _user(db, role):
    email = f"{role.value}@example.test"
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return existing
    u = User(full_name=f"{role.value} user", email=email, hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return u


def make_wo(db, number, status=WOStatus.IN_PRODUCTION):
    cust = Customer(customer_code=f"C-{number}", name="Cust")
    part = Part(part_number=f"P-{number}", description="p")
    db.add_all([cust, part])
    db.flush()
    order = Order(oar_number=f"OAR-{number}", customer_id=cust.id, part_id=part.id, customer_po="PO",
                  po_qty=10, max_batch_size=10, status=OrderStatus.ACCEPT)
    db.add(order)
    db.flush()
    wo = WorkOrder(wo_number=number, order_id=order.id, physical_wo_qty=10, current_stage="F1",
                   projected_final_good=10, status=status)
    db.add(wo)
    db.flush()
    for seq, stage in enumerate(["F1", "F2", "DISPATCH"], start=1):
        db.add(WORoute(work_order_id=wo.id, stage=stage, sequence=seq, stage_target_qty=10))
    db.add(StageWIP(work_order_id=wo.id, stage="F1", ent_qty=10, ok_qty=0, inproc_qty=10,
                    onhand_qty=0, rejected_qty=0, available_wip=10))
    db.commit()
    return wo


def _material(db, code="M1"):
    m = cc.ContinuousCastingMaterial(material_code=code, grade="SG450", section="ROUND", stock_dimension_a_mm=200)
    db.add(m)
    db.commit()
    return m


def routing_fields(mat, wo="WO-1001", **kw):
    base = dict(wo_number=wo, validated_material_id=mat.id, required_grade="SG450", required_section="ROUND",
                finished_dimension_a_mm=80, finished_axial_length_mm=100, machining_stock_a_mm=2,
                machining_stock_b_mm=2, planned_blanks=10, planned_cuts=10, kerf_mm=3, end_trim_mm=0)
    base.update(kw)
    return base


def accepted_units(db, mat, lengths, accept=True):
    store = _user(db, UserRole.STORE)
    r = InwardSvc.create_inward(db, CCInwardCreate(material_id=mat.id, unit_lengths_mm=lengths), store)
    inward = db.query(Inward).filter_by(inward_number=r.inward_number).one()
    if accept:
        inward.qa_status = "ACCEPTED"
        db.commit()
    return [db.query(Unit).filter_by(unit_number=u.unit_number).one() for u in r.units]


def split_off(db, unit, x):
    """Lower a unit's remaining length through a real SPLIT (x mm move to a child unit). The ledger
    stays consistent, unlike writing the cached remaining directly."""
    from app.schemas.continuous_casting import CCSplitCreate
    from app.services.continuous_casting_split_service import ContinuousCastingSplitService
    return ContinuousCastingSplitService.split(
        db, CCSplitCreate(stock_unit_id=unit.id, inward_id=unit.inward_id, length_mm=x), _user(db, UserRole.STORE))


def new_routing(db, mat, wo="WO-1001"):
    r = RouteSvc.create_routing(db, CCRoutingCreate(**routing_fields(mat, wo)), _user(db, UserRole.ENGINEERING))
    return uuid.UUID(r.routing_id)


def supersede(db, mat, wo="WO-1001", reason="design change"):
    r = RouteSvc.supersede_routing(db, CCRoutingSupersede(**routing_fields(mat, wo), reason=reason),
                                   _user(db, UserRole.ENGINEERING))
    return uuid.UUID(r.routing_id)


def allocate(db, rid, unit, planned):
    a = AllocSvc.create_allocation(
        db, CCAllocationCreate(routing_id=rid, stock_unit_id=unit.id, planned_length_mm=planned),
        _user(db, UserRole.PLANNER))
    return db.query(Alloc).filter_by(allocation_number=a.allocation_number).one()


def reserve(db, rid, alloc, x, user=None, **kw):
    return Rsv.reserve(db, CCReserveCreate(routing_id=rid, allocation_id=alloc.id, length_mm=x, **kw),
                       user or _user(db, UserRole.PLANNER))


def release(db, rid, alloc, x, user=None, **kw):
    return Rsv.release(db, CCReleaseCreate(routing_id=rid, allocation_id=alloc.id, length_mm=x, **kw),
                       user or _user(db, UserRole.PLANNER))


def _ledger_row(db, unit, alloc, mtype, length):
    db.add(Ledger(transaction_number=cc.next_cc_ledger_transaction_number(db), movement_type=mtype,
                  inward_id=unit.inward_id, stock_unit_id=unit.id, allocation_id=alloc.id if alloc else None,
                  length_mm=length, unit_remaining_after_mm=unit.remaining_length_mm))
    db.flush()


def simulate_issue(db, alloc, unit, x):
    """Stand-in for the (later) ISSUE service: reserved -> issued, with its ledger row."""
    alloc.reserved_length_mm -= x; alloc.issued_length_mm += x
    unit.reserved_length_mm -= x; unit.issued_length_mm += x
    alloc.status = "ISSUED"
    _ledger_row(db, unit, alloc, "ISSUE", x)
    db.commit()


def simulate_cut(db, alloc, unit, x):
    """Stand-in for the (later) CUT_CONSUME service: issued -> consumed, remaining down."""
    alloc.issued_length_mm -= x; alloc.consumed_length_mm += x
    unit.issued_length_mm -= x; unit.consumed_length_mm += x; unit.remaining_length_mm -= x
    alloc.status = "PARTIALLY_CONSUMED"
    _ledger_row(db, unit, alloc, "CUT_CONSUME", x)
    db.commit()


def count(db, table):
    return db.execute(select(func.count()).select_from(Base.metadata.tables[table])).scalar()


def rows(db, table):
    return sorted((tuple(r) for r in db.execute(select(Base.metadata.tables[table])).all()), key=repr)


def oms_state(db):
    return {t: rows(db, t) for t in OMS_TABLES}


def snapshot(db):
    return {t: rows(db, t) for t in ["cc_stock_units", "cc_allocations", "cc_stock_ledger", "audit_logs"]}


def fresh(db, model, pk):
    db.expire_all()
    return db.get(model, pk)


def ledger_totals(db, unit_id):
    out = {}
    for t, s in db.query(Ledger.movement_type, func.sum(Ledger.length_mm)).filter(
            Ledger.stock_unit_id == unit_id).group_by(Ledger.movement_type).all():
        out[t] = int(s)
    return out


def assert_reconciled(db, unit):
    """Independent re-derivation (not the service's own function)."""
    unit = fresh(db, Unit, unit.id)
    t = ledger_totals(db, unit.id)
    assert unit.reserved_length_mm == t.get("RESERVE", 0) - t.get("RELEASE", 0) - t.get("ISSUE", 0)
    assert unit.issued_length_mm == t.get("ISSUE", 0) - t.get("RETURN", 0) - t.get("CUT_CONSUME", 0)
    assert unit.consumed_length_mm == t.get("CUT_CONSUME", 0)
    allocs = db.query(Alloc).filter_by(stock_unit_id=unit.id).all()
    assert unit.reserved_length_mm == sum(a.reserved_length_mm for a in allocs)
    assert unit.issued_length_mm == sum(a.issued_length_mm for a in allocs)
    assert unit.reserved_length_mm + unit.issued_length_mm <= unit.remaining_length_mm
    assert unit.reserved_length_mm >= 0 and unit.issued_length_mm >= 0


@pytest.fixture()
def world(db):
    """One WO, one ACCEPTED 1000 mm unit, an ACTIVE routing and one 600 mm allocation."""
    mat = _material(db)
    wo = make_wo(db, "WO-1001")
    (unit,) = accepted_units(db, mat, [1000])
    rid = new_routing(db, mat)
    alloc = allocate(db, rid, unit, 600)
    return dict(db=db, mat=mat, wo=wo, unit=unit, rid=rid, alloc=alloc)


# ------------------------------------------------------------------ RESERVE: success paths
def test_full_reserve(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    r = reserve(db, rid, alloc, 600)
    assert r.movement_type == "RESERVE" and r.length_mm == 600 and r.reconciled is True
    assert r.allocation_status == "RESERVED" and r.ledger_transaction_number == "TXN-000002"
    assert (r.allocation_reserved_length_mm, r.unit_reserved_length_mm) == (600, 600)
    assert (r.unit_remaining_length_mm, r.unit_free_length_mm) == (1000, 400)
    assert r.ledger_reserved_length_mm == 600
    assert_reconciled(db, unit)


def test_partial_reserves_accumulate(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 200)
    r = reserve(db, rid, alloc, 300)
    assert (r.allocation_reserved_length_mm, r.unit_reserved_length_mm, r.unit_free_length_mm) == (500, 500, 500)
    assert r.allocation_status == "RESERVED"
    assert db.query(Ledger).filter_by(movement_type="RESERVE").count() == 2
    assert_reconciled(db, unit)


def test_reserve_cannot_exceed_the_planned_allocation(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        reserve(db, rid, alloc, 601)
    assert e.value.status_code == 400 and "600" in e.value.detail and snapshot(db) == before
    reserve(db, rid, alloc, 400)
    with pytest.raises(HTTPException) as e:                       # cumulative, not per call
        reserve(db, rid, alloc, 201)
    assert e.value.status_code == 400 and "200" in e.value.detail
    reserve(db, rid, alloc, 200)
    assert_reconciled(db, unit)


def test_issued_and_consumed_length_use_up_the_plan_too(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 300)
    simulate_issue(db, alloc, unit, 200)                          # reserved 100, issued 200
    simulate_cut(db, alloc, unit, 50)                             # issued 150, consumed 50
    with pytest.raises(HTTPException) as e:                       # plan left = 600 - 100 - 150 - 50 = 300
        reserve(db, rid, alloc, 301)
    assert e.value.status_code == 400 and "300" in e.value.detail
    reserve(db, rid, alloc, 300)
    assert_reconciled(db, unit)


def test_reserve_cannot_exceed_free_physical_length(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    make_wo(db, "WO-1002")
    (unit,) = accepted_units(db, mat, [1000])
    rid, rid2 = new_routing(db, mat), new_routing(db, mat, "WO-1002")
    a1, a2 = allocate(db, rid, unit, 500), allocate(db, rid2, unit, 500)
    split_off(db, unit, 200)                                      # 200 mm leave the bar through a real SPLIT
    reserve(db, rid, a1, 500)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        reserve(db, rid2, a2, 500)
    assert e.value.status_code == 400 and "300" in e.value.detail and "physical length" in e.value.detail
    assert snapshot(db) == before
    reserve(db, rid2, a2, 300)
    final = fresh(db, Unit, unit.id)
    assert final.reserved_length_mm == final.remaining_length_mm == 800


def test_a_fully_issued_plan_blocks_further_reservation(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 600)
    simulate_issue(db, alloc, unit, 600)
    issued = fresh(db, Unit, unit.id)
    assert (issued.issued_length_mm, issued.reserved_length_mm) == (600, 0)
    with pytest.raises(HTTPException) as e:                       # the whole plan is already issued
        reserve(db, rid, alloc, 1)
    assert e.value.status_code == 400 and "0 mm of the planned 600" in e.value.detail


# ------------------------------------------------------------------ RESERVE: rejections
def test_pending_qa_stock_is_rejected(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    db.query(Inward).one().qa_status = "PENDING_QA"
    db.commit()
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        reserve(db, rid, alloc, 100)
    assert e.value.status_code == 400 and "PENDING_QA" in e.value.detail and snapshot(db) == before


@pytest.mark.parametrize("qa", ["REJECTED", "ON_HOLD"])
def test_other_non_accepted_qa_is_rejected(world, qa):
    db = world["db"]
    db.query(Inward).one().qa_status = qa
    db.commit()
    with pytest.raises(HTTPException) as e:
        reserve(db, world["rid"], world["alloc"], 100)
    assert e.value.status_code == 400 and qa in e.value.detail


@pytest.mark.parametrize("state", ["ON_HOLD", "SCRAPPED", "CONSUMED"])
def test_unit_that_is_not_in_stock_is_rejected(world, state):
    db = world["db"]
    fresh(db, Unit, world["unit"].id).status = state
    db.commit()
    with pytest.raises(HTTPException) as e:
        reserve(db, world["rid"], world["alloc"], 100)
    assert e.value.status_code == 400 and state in e.value.detail and "IN_STOCK" in e.value.detail


def test_superseded_routing_rejects_new_reservations(world):
    db = world["db"]
    supersede(db, world["mat"])
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        reserve(db, world["rid"], world["alloc"], 100)
    assert e.value.status_code == 400 and "SUPERSEDED" in e.value.detail and snapshot(db) == before


def test_non_active_routing_states_reject_new_reservations(world):
    db = world["db"]
    for state in ("DRAFT", "SUPERSEDED"):
        db.query(Routing).one().status = state
        db.commit()
        with pytest.raises(HTTPException) as e:
            reserve(db, world["rid"], world["alloc"], 100)
        assert e.value.status_code == 400 and state in e.value.detail


def test_non_continuous_casting_routing_cannot_reserve(world):
    db = world["db"]
    db.query(Routing).one().material_source = "F1_PRODUCTION"
    db.commit()
    with pytest.raises(HTTPException) as e:
        reserve(db, world["rid"], world["alloc"], 100)
    assert e.value.status_code == 400 and "CONTINUOUS_CASTING" in e.value.detail


@pytest.mark.parametrize("state", [WOStatus.CLOSED, WOStatus.DISPATCHED])
def test_closed_work_order_cannot_reserve(world, state):
    db = world["db"]
    fresh(db, WorkOrder, world["wo"].id).status = state
    db.commit()
    with pytest.raises(HTTPException) as e:
        reserve(db, world["rid"], world["alloc"], 100)
    assert e.value.status_code == 400


def test_allocation_must_belong_to_the_routing_supplied(world):
    db = world["db"]
    make_wo(db, "WO-1002")
    other = new_routing(db, world["mat"], "WO-1002")
    with pytest.raises(HTTPException) as e:
        reserve(db, other, world["alloc"], 100)
    assert e.value.status_code == 400 and "does not belong" in e.value.detail
    with pytest.raises(HTTPException) as e:
        release(db, other, world["alloc"], 100)
    assert e.value.status_code == 400


def test_unknown_allocation_is_404(world):
    db = world["db"]
    with pytest.raises(HTTPException) as e:
        Rsv.reserve(db, CCReserveCreate(routing_id=world["rid"], allocation_id=uuid.uuid4(), length_mm=10),
                    _user(db, UserRole.PLANNER))
    assert e.value.status_code == 404


@pytest.mark.parametrize("bad", [0, -5, 1.5, "abc", None])
def test_schema_rejects_non_positive_or_non_integer_length(world, bad):
    with pytest.raises(ValidationError):
        CCReserveCreate(routing_id=world["rid"], allocation_id=world["alloc"].id, length_mm=bad)
    with pytest.raises(ValidationError):
        CCReleaseCreate(routing_id=world["rid"], allocation_id=world["alloc"].id, length_mm=bad)


@pytest.mark.parametrize("bad", [0, -1, True])
def test_service_rejects_bad_lengths_even_without_schema_validation(world, bad):
    db = world["db"]
    raw = CCReserveCreate.model_construct(routing_id=world["rid"], allocation_id=world["alloc"].id,
                                          length_mm=bad, reason=None)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Rsv.reserve(db, raw, _user(db, UserRole.PLANNER))
    assert e.value.status_code == 400 and snapshot(db) == before


def test_unknown_fields_are_refused(world):
    with pytest.raises(ValidationError):
        CCReserveCreate(routing_id=world["rid"], allocation_id=world["alloc"].id, length_mm=10,
                        client_request_id="x")                  # no approved idempotency field


# ------------------------------------------------------------------ RESERVE: ledger + balances
def test_reserve_writes_exactly_one_correct_ledger_row(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    before = count(db, "cc_stock_ledger")
    user = _user(db, UserRole.PLANNER)
    r = reserve(db, rid, alloc, 250, user=user, reason="WO-1001 first lot")
    assert count(db, "cc_stock_ledger") == before + 1
    row = db.query(Ledger).filter_by(transaction_number=r.ledger_transaction_number).one()
    assert row.movement_type == "RESERVE" and row.length_mm == 250 and row.piece_qty is None
    assert row.inward_id == unit.inward_id and row.stock_unit_id == unit.id and row.allocation_id == alloc.id
    assert row.unit_remaining_after_mm == 1000                    # physical length untouched
    assert row.performed_by_id == user.id and row.performed_by_name == user.full_name
    assert row.reason == "WO-1001 first lot" and row.client_request_id is None and row.created_at is not None
    assert alloc.allocation_number in row.reference and "WO-1001" in row.reference and "routing v1" in row.reference
    wo = db.get(Routing, db.get(Alloc, row.allocation_id).routing_id).work_order
    assert wo.wo_number == "WO-1001"                              # WO reachable through allocation -> routing
    audit = db.query(AuditLog).filter(AuditLog.action == "CC_RESERVE").one()
    assert audit.entity_id == alloc.allocation_number and audit.user_id == user.id


def test_default_reason_is_recorded_when_none_is_given(world):
    r = reserve(world["db"], world["rid"], world["alloc"], 100)
    assert "Reserve for WO-1001 routing v1" in world["db"].query(Ledger).filter_by(
        transaction_number=r.ledger_transaction_number).one().reason


def test_reserve_leaves_physical_remaining_issued_and_consumed_unchanged(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 300)
    simulate_issue(db, alloc, unit, 100)
    simulate_cut(db, alloc, unit, 40)
    before = fresh(db, Unit, unit.id)
    snap = (before.remaining_length_mm, before.issued_length_mm, before.consumed_length_mm, before.original_length_mm)
    a_before = fresh(db, Alloc, alloc.id)
    asnap = (a_before.issued_length_mm, a_before.consumed_length_mm, a_before.planned_length_mm)
    reserve(db, rid, alloc, 150)
    after = fresh(db, Unit, unit.id)
    assert (after.remaining_length_mm, after.issued_length_mm, after.consumed_length_mm,
            after.original_length_mm) == snap
    a_after = fresh(db, Alloc, alloc.id)
    assert (a_after.issued_length_mm, a_after.consumed_length_mm, a_after.planned_length_mm) == asnap
    assert snap == (960, 60, 40, 1000)                              # 1000 - 40 cut; issued 100 - 40
    assert after.reserved_length_mm == 200 + 150                    # reserved 300 - 100 issued, then +150
    assert_reconciled(db, after)


# ------------------------------------------------------------------ RELEASE
def test_partial_release(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 600)
    r = release(db, rid, alloc, 200)
    assert r.movement_type == "RELEASE" and r.length_mm == 200
    assert (r.allocation_reserved_length_mm, r.unit_reserved_length_mm) == (400, 400)
    assert r.allocation_status == "RESERVED" and r.unit_free_length_mm == 600
    assert_reconciled(db, unit)


def test_the_spec_example_reserved_642_release_200_leaves_442(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    (unit,) = accepted_units(db, mat, [1000])
    rid = new_routing(db, mat)
    alloc = allocate(db, rid, unit, 642)
    reserve(db, rid, alloc, 642)
    r = release(db, rid, alloc, 200)
    assert r.allocation_reserved_length_mm == 442 and r.unit_reserved_length_mm == 442
    assert_reconciled(db, unit)


def test_full_release_returns_the_allocation_to_planned_and_it_can_be_reserved_again(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 600)
    r = release(db, rid, alloc, 600)
    assert (r.allocation_reserved_length_mm, r.unit_reserved_length_mm, r.unit_free_length_mm) == (0, 0, 1000)
    assert r.allocation_status == "PLANNED"
    assert reserve(db, rid, alloc, 600).allocation_status == "RESERVED"
    assert_reconciled(db, unit)


def test_release_cannot_exceed_the_currently_reserved_quantity(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    with pytest.raises(HTTPException) as e:                       # nothing reserved yet
        release(db, rid, alloc, 1)
    assert e.value.status_code == 400 and "0 mm is currently reserved" in e.value.detail
    reserve(db, rid, alloc, 300)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        release(db, rid, alloc, 301)
    assert e.value.status_code == 400 and "300" in e.value.detail and snapshot(db) == before


def test_release_never_touches_issued_or_consumed_material(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 500)
    simulate_issue(db, alloc, unit, 300)                          # reserved 200, issued 300
    simulate_cut(db, alloc, unit, 100)                            # issued 200, consumed 100
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        release(db, rid, alloc, 201)
    assert e.value.status_code == 400 and "issued 200 mm and consumed 100 mm cannot be released" in e.value.detail
    assert snapshot(db) == before
    r = release(db, rid, alloc, 200)                              # exactly the reserved remainder
    assert (r.unit_issued_length_mm, r.unit_consumed_length_mm) == (200, 100)
    assert (r.allocation_issued_length_mm, r.allocation_consumed_length_mm) == (200, 100)
    assert r.unit_remaining_length_mm == 900 and r.allocation_status == "PARTIALLY_CONSUMED"
    assert_reconciled(db, unit)


def test_release_writes_exactly_one_correct_ledger_row(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 400)
    before = count(db, "cc_stock_ledger")
    user = _user(db, UserRole.PLANNER)
    r = release(db, rid, alloc, 150, user=user, reason="WO plan reduced")
    assert count(db, "cc_stock_ledger") == before + 1
    row = db.query(Ledger).filter_by(transaction_number=r.ledger_transaction_number).one()
    assert row.movement_type == "RELEASE" and row.length_mm == 150
    assert row.inward_id == unit.inward_id and row.stock_unit_id == unit.id and row.allocation_id == alloc.id
    assert row.unit_remaining_after_mm == 1000 and row.reason == "WO plan reduced"
    assert row.performed_by_id == user.id and row.client_request_id is None
    assert fresh(db, Unit, unit.id).remaining_length_mm == 1000    # a release never gives length back
    assert db.query(AuditLog).filter(AuditLog.action == "CC_RELEASE").one().entity_id == alloc.allocation_number


def test_release_is_allowed_when_qa_changed_or_the_work_order_closed(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 300)
    db.query(Inward).one().qa_status = "ON_HOLD"
    fresh(db, WorkOrder, world["wo"].id).status = WOStatus.CLOSED
    db.commit()
    assert release(db, rid, alloc, 300).unit_reserved_length_mm == 0


# ------------------------------------------------------------------ supersession + release
def test_superseded_routing_reserved_stock_is_released_through_the_ledger(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 600)
    supersede(db, world["mat"])
    assert fresh(db, Unit, unit.id).reserved_length_mm == 600     # supersession alone changes nothing
    ledger_before = count(db, "cc_stock_ledger")
    res = Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.PLANNER))
    assert res.allocations_released == 1 and res.total_released_length_mm == 600
    assert count(db, "cc_stock_ledger") == ledger_before + 1       # an explicit RELEASE row, no silent edit
    row = db.query(Ledger).filter_by(movement_type="RELEASE").one()
    assert row.length_mm == 600 and row.allocation_id == alloc.id and "superseded" in row.reason
    unit_after, alloc_after = fresh(db, Unit, unit.id), fresh(db, Alloc, alloc.id)
    assert (unit_after.reserved_length_mm, alloc_after.reserved_length_mm) == (0, 0)
    assert alloc_after.status == "RELEASED" and unit_after.remaining_length_mm == 1000
    assert_reconciled(db, unit)


def test_a_single_allocation_on_a_superseded_routing_can_be_partly_released(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 600)
    supersede(db, world["mat"])
    r = release(db, rid, alloc, 250)
    assert r.allocation_reserved_length_mm == 350 and r.allocation_status == "RESERVED"
    assert_reconciled(db, unit)


def test_unreserved_plan_on_a_superseded_routing_creates_no_release(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    supersede(db, world["mat"])                                    # the 600 mm plan was never reserved
    before = snapshot(db)
    res = Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.PLANNER))
    assert res.allocations_released == 0 and res.total_released_length_mm == 0 and res.releases == []
    assert db.query(Ledger).filter_by(movement_type="RELEASE").count() == 0
    assert snapshot(db) == before                                  # not even an audit row
    assert fresh(db, Alloc, alloc.id).status == "PLANNED"


def test_bulk_release_handles_only_reserved_allocations_across_several_units(db):
    mat = _material(db)
    make_wo(db, "WO-1001")
    u1, u2, u3 = accepted_units(db, mat, [1000, 1000, 1000])
    rid = new_routing(db, mat)
    a1, a2, a3 = allocate(db, rid, u1, 500), allocate(db, rid, u2, 400), allocate(db, rid, u3, 100)
    reserve(db, rid, a1, 300)
    reserve(db, rid, a2, 400)                                       # a1 partly reserved, a2 fully, a3 never
    supersede(db, mat)
    res = Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.ADMIN))
    assert fresh(db, Alloc, a3.id).status == "PLANNED"              # never reserved: left alone
    assert res.allocations_released == 2 and res.total_released_length_mm == 700
    assert {r.length_mm for r in res.releases} == {300, 400}
    for u in (u1, u2):
        assert fresh(db, Unit, u.id).reserved_length_mm == 0
        assert_reconciled(db, u)
    released = db.query(Ledger).filter_by(movement_type="RELEASE").order_by(Ledger.transaction_number).all()
    assert [str(r.stock_unit_id) for r in released] == sorted(str(r.stock_unit_id) for r in released)


def test_bulk_release_rejects_an_active_or_unknown_routing(world):
    db, rid = world["db"], world["rid"]
    with pytest.raises(HTTPException) as e:
        Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.PLANNER))
    assert e.value.status_code == 400 and "ACTIVE" in e.value.detail
    with pytest.raises(HTTPException) as e:
        Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=uuid.uuid4()), _user(db, UserRole.PLANNER))
    assert e.value.status_code == 404


def test_releasing_twice_is_safe_the_second_call_finds_nothing(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 600)
    supersede(db, world["mat"])
    req = CCRoutingReleaseCreate(routing_id=rid)
    assert Rsv.release_superseded_routing(db, req, _user(db, UserRole.PLANNER)).allocations_released == 1
    again = Rsv.release_superseded_routing(db, req, _user(db, UserRole.PLANNER))
    assert again.allocations_released == 0 and db.query(Ledger).filter_by(movement_type="RELEASE").count() == 1


def test_after_release_a_new_routing_can_use_the_same_stock(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 600)
    new_rid = supersede(db, world["mat"])
    Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.PLANNER))
    a_new = allocate(db, new_rid, unit, 1000)
    assert reserve(db, new_rid, a_new, 1000).unit_reserved_length_mm == 1000
    assert_reconciled(db, unit)


# ------------------------------------------------------------------ many allocations on one unit
def test_many_allocations_on_one_unit_stay_reconciled(db):
    mat = _material(db)
    for n in (1, 2, 3, 4):
        make_wo(db, f"WO-100{n}")
    (unit,) = accepted_units(db, mat, [1000])
    rids = {n: new_routing(db, mat, f"WO-100{n}") for n in (1, 2, 3, 4)}
    allocs = {n: allocate(db, rids[n], unit, 250) for n in (1, 2, 3, 4)}
    steps = [("r", 1, 250), ("r", 2, 100), ("r", 3, 250), ("l", 1, 100), ("r", 2, 150), ("l", 3, 250),
             ("r", 4, 250), ("l", 2, 50), ("r", 1, 100), ("l", 4, 100)]
    for kind, n, x in steps:
        (reserve if kind == "r" else release)(db, rids[n], allocs[n], x)
        assert_reconciled(db, unit)
    final = fresh(db, Unit, unit.id)
    per_alloc = {n: fresh(db, Alloc, a.id).reserved_length_mm for n, a in allocs.items()}
    assert per_alloc == {1: 250, 2: 200, 3: 0, 4: 150}
    assert final.reserved_length_mm == sum(per_alloc.values()) == 600
    t = ledger_totals(db, unit.id)
    assert final.reserved_length_mm == t["RESERVE"] - t["RELEASE"]
    assert final.remaining_length_mm == 1000


# ------------------------------------------------------------------ roles
@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.PLANNER])
def test_reserve_and_release_roles_allowed(world, role):
    db = world["db"]
    user = _user(db, role)
    assert reserve(db, world["rid"], world["alloc"], 100, user=user).success
    assert release(db, world["rid"], world["alloc"], 100, user=user).success


@pytest.mark.parametrize("role", [UserRole.STORE, UserRole.ENGINEERING, UserRole.PRODUCTION_MANAGER,
                                  UserRole.QA, UserRole.DISPATCH, UserRole.CEO])
def test_other_roles_are_rejected_with_403(world, role):
    db = world["db"]
    reserve(db, world["rid"], world["alloc"], 100)
    user = _user(db, role)
    before = snapshot(db)
    for op in (reserve, release):
        with pytest.raises(HTTPException) as e:
            op(db, world["rid"], world["alloc"], 50, user=user)
        assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=world["rid"]), user)
    assert e.value.status_code == 403 and snapshot(db) == before


def test_anonymous_is_rejected(world):
    with pytest.raises(HTTPException) as e:
        Rsv.reserve(world["db"], CCReserveCreate(routing_id=world["rid"], allocation_id=world["alloc"].id,
                                                 length_mm=10), None)
    assert e.value.status_code == 403


# ------------------------------------------------------------------ atomicity / rollback
def _raising_listener(model, event_name):
    def listener(mapper, connection, target):
        raise RuntimeError(f"injected {event_name} failure")
    event.listen(model, event_name, listener)
    return lambda: event.remove(model, event_name, listener)


@pytest.mark.parametrize("op", ["reserve", "release"])
def test_rollback_when_the_ledger_insert_fails(world, op):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    if op == "release":
        reserve(db, rid, alloc, 400)
    before = snapshot(db)
    off = _raising_listener(Ledger, "before_insert")
    try:
        with pytest.raises(RuntimeError):
            (reserve if op == "reserve" else release)(db, rid, alloc, 100)
    finally:
        off()
    assert snapshot(db) == before                                  # balances, ledger and audit all unchanged
    assert_reconciled(db, unit)


@pytest.mark.parametrize("op", ["reserve", "release"])
def test_rollback_when_the_balance_update_fails(world, op):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    if op == "release":
        reserve(db, rid, alloc, 400)
    before = snapshot(db)
    off = _raising_listener(Unit, "after_update")                  # fires after the UPDATE ran in the transaction
    try:
        with pytest.raises(RuntimeError):
            (reserve if op == "reserve" else release)(db, rid, alloc, 100)
    finally:
        off()
    assert snapshot(db) == before
    assert_reconciled(db, unit)


def test_rollback_after_everything_was_flushed(world, monkeypatch):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    before = snapshot(db)
    seen = {}

    def late(*a, **k):
        seen["ledger_rows_in_tx"] = count(db, "cc_stock_ledger")
        raise RuntimeError("late failure")

    monkeypatch.setattr(rv_svc, "CCStockMovementResult", late)
    with pytest.raises(RuntimeError):
        reserve(db, rid, alloc, 100)
    assert seen["ledger_rows_in_tx"] == len(before["cc_stock_ledger"]) + 1     # it really was in the transaction
    assert snapshot(db) == before


def test_reconciliation_mismatch_rolls_everything_back(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    before = snapshot(db)

    def skew(mapper, connection, target):
        target.length_mm = target.length_mm + 1                    # ledger now disagrees with the cached balance

    event.listen(Ledger, "before_insert", skew)
    try:
        with pytest.raises(HTTPException) as e:
            reserve(db, rid, alloc, 100)
    finally:
        event.remove(Ledger, "before_insert", skew)
    assert e.value.status_code == 500 and "reconciliation" in e.value.detail.lower()
    assert snapshot(db) == before
    assert reserve(db, rid, alloc, 100).reconciled is True         # and the system is healthy afterwards


def test_a_pre_existing_drift_blocks_the_operation_instead_of_hiding_it(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    fresh(db, Unit, unit.id).reserved_length_mm = 50               # cached balance with no ledger behind it
    db.commit()
    with pytest.raises(HTTPException) as e:
        reserve(db, rid, alloc, 100)
    assert e.value.status_code == 500 and count(db, "cc_stock_ledger") == 1


# ------------------------------------------------------------------ number collisions
def _flaky(monkeypatch, first_values):
    real = rv_svc.next_cc_ledger_transaction_number
    calls = []

    def fake(db):
        calls.append(1)
        return first_values[len(calls) - 1] if len(calls) <= len(first_values) else real(db)

    monkeypatch.setattr(rv_svc, "next_cc_ledger_transaction_number", fake)
    return calls


def test_ledger_number_collision_is_retried_and_recovers(world, monkeypatch):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    calls = _flaky(monkeypatch, ["TXN-000001"])                    # already used by the INWARD row
    r = reserve(db, rid, alloc, 100)
    assert len(calls) == 2 and r.ledger_transaction_number == "TXN-000002"
    assert db.query(Ledger).filter_by(movement_type="RESERVE").count() == 1
    assert_reconciled(db, unit)


def test_persistent_collision_is_a_controlled_409_not_a_500(world, monkeypatch):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    before = snapshot(db)
    calls = _flaky(monkeypatch, ["TXN-000001"] * 10)
    with pytest.raises(HTTPException) as e:
        reserve(db, rid, alloc, 100)
    assert e.value.status_code == 409 and len(calls) == rv_svc.CC_NUMBER_MAX_ATTEMPTS
    assert snapshot(db) == before


def test_release_collision_is_controlled_too_and_bulk_retries_whole(world, monkeypatch):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    reserve(db, rid, alloc, 300)
    supersede(db, world["mat"])
    calls = _flaky(monkeypatch, ["TXN-000001"])
    res = Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.PLANNER))
    assert res.allocations_released == 1 and len(calls) == 2
    assert_reconciled(db, unit)


def test_no_idempotency_key_is_involved_so_the_strip_on_none_bug_cannot_occur(world, monkeypatch):
    src = Path(rv_svc.__file__).read_text(encoding="utf-8")
    assert "req.client_request_id" not in src and ".client_request_id" not in src   # never read, never .strip()ed
    assert "client_request_id" not in CCReserveCreate.model_fields
    assert "client_request_id" not in CCReleaseCreate.model_fields
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    _flaky(monkeypatch, ["TXN-000001"] * 10)
    with pytest.raises(HTTPException) as e:                        # collision path with no key at all
        reserve(db, rid, alloc, 100)
    assert e.value.status_code == 409


# ------------------------------------------------------------------ OMS untouched
def test_existing_oms_rows_are_untouched(world):
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    before = oms_state(db)
    reserve(db, rid, alloc, 400)
    release(db, rid, alloc, 100)
    supersede(db, world["mat"])
    Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.PLANNER))
    assert oms_state(db) == before                                  # WO, WORoute, StageWIP, movements: identical
    assert count(db, "orders") == 1 and count(db, "work_orders") == 1


def test_service_touches_oms_only_through_a_read_of_workorder():
    src = Path(rv_svc.__file__).read_text(encoding="utf-8")
    modules = dict(re.findall(r"^\s*from\s+(\S+)\s+import\s+(.+?)$", src, flags=re.M))
    for banned in ("app.services.production_service", "app.services.work_order_service",
                   "app.services.oms_integration_service", "app.services.rejection_service",
                   "app.services.operations_service", "app.models.production_movement", "app.models.nc",
                   "app.models.production", "app.models.order"):
        assert banned not in modules, banned
    assert {n.strip() for n in modules["app.models.work_order"].split(",")} == {"WorkOrder", "WOStatus"}


# ------------------------------------------------------------------ locking + stale reads
def test_reserve_and_release_lock_unit_then_allocation_then_routing(world, monkeypatch):
    db, rid, alloc = world["db"], world["rid"], world["alloc"]
    order = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    reserve(db, rid, alloc, 100)
    assert order == [Unit, Alloc, Routing]
    order.clear()
    release(db, rid, alloc, 100)
    assert order == [Unit, Alloc, Routing]


def test_bulk_release_repeats_the_same_lock_order_for_every_allocation(db, monkeypatch):
    mat = _material(db)
    make_wo(db, "WO-1001")
    u1, u2 = accepted_units(db, mat, [1000, 1000])
    rid = new_routing(db, mat)
    for u in (u1, u2):
        reserve(db, rid, allocate(db, rid, u, 300), 300)
    supersede(db, mat)
    order = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    Rsv.release_superseded_routing(db, CCRoutingReleaseCreate(routing_id=rid), _user(db, UserRole.PLANNER))
    assert order == [Unit, Alloc, Routing] * 2


def test_balances_are_re_read_after_the_lock_not_taken_from_an_earlier_read(world):
    """A session holding a stale copy of the unit must still be checked against the real balance."""
    db, unit, alloc, rid = world["db"], world["unit"], world["alloc"], world["rid"]
    stale = db.get(Unit, unit.id)
    assert stale.reserved_length_mm == 0
    db.execute(Base.metadata.tables["cc_stock_units"].update().where(
        Base.metadata.tables["cc_stock_units"].c.id == str(unit.id)).values(reserved_length_mm=900, remaining_length_mm=1000))
    db.execute(Base.metadata.tables["cc_allocations"].update().where(
        Base.metadata.tables["cc_allocations"].c.id == str(alloc.id)).values(reserved_length_mm=0))
    db.execute(Base.metadata.tables["cc_stock_ledger"].insert().values(
        id=str(uuid.uuid4()), transaction_number="TXN-000900", movement_type="RESERVE", inward_id=str(unit.inward_id),
        stock_unit_id=str(unit.id), allocation_id=None, length_mm=900, unit_remaining_after_mm=1000))
    assert stale.reserved_length_mm == 0                           # the ORM copy really is stale
    with pytest.raises(HTTPException) as e:
        reserve(db, rid, alloc, 200)                               # only 100 mm is truly free
    assert e.value.status_code == 400 and "100" in e.value.detail


def _two_allocations_on_one_unit(s1):
    """Unit remaining 800 after a real SPLIT of 200 mm, with two 500 mm plans against it."""
    mat = _material(s1)
    make_wo(s1, "WO-1001")
    make_wo(s1, "WO-1002")
    (unit,) = accepted_units(s1, mat, [1000])
    r1, r2 = new_routing(s1, mat, "WO-1001"), new_routing(s1, mat, "WO-1002")
    a1, a2 = allocate(s1, r1, unit, 500), allocate(s1, r2, unit, 500)
    split_off(s1, unit, 200)
    return unit.id, (r1, a1.id), (r2, a2.id)


def test_conflicting_reservations_from_two_connections_cannot_exceed_remaining(shared):
    s1, s2 = shared
    unit_id, (r1, a1), (r2, a2) = _two_allocations_on_one_unit(s1)
    planner1, planner2 = _user(s1, UserRole.PLANNER), s2.get(User, _user(s1, UserRole.PLANNER).id)
    stale = s2.get(Unit, unit_id)                                   # connection B loads the unit first
    assert stale.reserved_length_mm == 0

    Rsv.reserve(s1, CCReserveCreate(routing_id=r1, allocation_id=a1, length_mm=500), planner1)   # A reserves 500
    assert stale.reserved_length_mm == 0                            # B's copy is now stale

    with pytest.raises(HTTPException) as e:                         # B believes 800 free; only 300 really is
        Rsv.reserve(s2, CCReserveCreate(routing_id=r2, allocation_id=a2, length_mm=500), planner2)
    assert e.value.status_code == 400 and "300" in e.value.detail
    Rsv.reserve(s2, CCReserveCreate(routing_id=r2, allocation_id=a2, length_mm=300), planner2)

    s1.expire_all()
    unit = s1.get(Unit, unit_id)
    assert unit.reserved_length_mm == 800 and unit.reserved_length_mm <= unit.remaining_length_mm
    assert unit.reserved_length_mm + unit.issued_length_mm <= unit.remaining_length_mm
    assert_reconciled(s1, unit)


def test_interleaved_reservations_from_two_connections_never_break_the_invariants(shared):
    s1, s2 = shared
    unit_id, (r1, a1), (r2, a2) = _two_allocations_on_one_unit(s1)
    users = {1: _user(s1, UserRole.PLANNER)}
    users[2] = s2.get(User, users[1].id)
    sessions = {1: (s1, r1, a1), 2: (s2, r2, a2)}
    accepted = rejected = 0
    for step in range(12):
        n = 1 + step % 2
        session, rid, aid = sessions[n]
        try:
            Rsv.reserve(session, CCReserveCreate(routing_id=rid, allocation_id=aid, length_mm=150), users[n])
            accepted += 1
        except HTTPException as e:
            assert e.status_code == 400
            rejected += 1
        s1.expire_all()
        unit = s1.get(Unit, unit_id)
        assert unit.reserved_length_mm <= unit.remaining_length_mm
        assert unit.reserved_length_mm + unit.issued_length_mm <= unit.remaining_length_mm
    assert accepted >= 1 and rejected >= 1                          # it did hit the limits
    final = s1.get(Unit, unit_id)
    assert final.reserved_length_mm == 150 * accepted == 750        # 5 x 150; the 6th would pass 800 mm
    assert_reconciled(s1, final)


def test_the_database_check_constraints_are_the_final_backstop(world):
    db, unit = world["db"], world["unit"]
    u = fresh(db, Unit, unit.id)
    u.reserved_length_mm = u.remaining_length_mm + 1               # bypassing the service entirely
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    u = fresh(db, Unit, unit.id)
    u.reserved_length_mm, u.issued_length_mm = 600, 401
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_no_database_file_is_used_by_the_shared_fixture(shared):
    s1, _ = shared
    url = s1.get_bind().url
    assert url.query.get("mode") == "memory" and url.query.get("cache") == "shared"
