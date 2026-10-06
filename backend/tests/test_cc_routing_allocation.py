"""Continuous Casting routing + allocation (Phase 3). Isolated in-memory SQLite only; the
app's configured database is never opened. SQLite does not enforce FKs by default and
ignores FOR UPDATE, so locking is verified by spying on the query call."""
import re
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
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
    CCAllocationCreate, CCInwardCreate, CCRoutingCreate, CCRoutingSupersede,
)
import app.services.continuous_casting_routing_service as rsvc
from app.services.continuous_casting_routing_service import (
    ContinuousCastingAllocationService as AllocSvc,
    ContinuousCastingRoutingService as RouteSvc,
    calculate_blank_length_mm, calculate_gross_required_length_mm,
)
from app.services.continuous_casting_service import ContinuousCastingInwardService as InwardSvc

OMS_TABLES = ["work_orders", "wo_routes", "stage_wips", "orders", "production_movements",
              "production_updates", "nc_records", "packing_records", "dispatches", "conversions"]


# ------------------------------------------------------------------ fixtures / helpers
@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert engine.url.database == ":memory:"
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _user(db, role):
    email = f"{role.value}@example.test"
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return existing
    u = User(full_name=f"{role.value} user", email=email, hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def engineer(db):
    return _user(db, UserRole.ENGINEERING)


@pytest.fixture()
def planner(db):
    return _user(db, UserRole.PLANNER)


@pytest.fixture()
def store(db):
    return _user(db, UserRole.STORE)


def _material(db, code="M1"):
    m = cc.ContinuousCastingMaterial(material_code=code, grade="SG450", section="ROUND", stock_dimension_a_mm=200)
    db.add(m)
    db.commit()
    return m


@pytest.fixture()
def mat(db):
    return _material(db)


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


@pytest.fixture()
def wo1(db):
    return make_wo(db, "WO-1001")


@pytest.fixture()
def wo2(db):
    return make_wo(db, "WO-1002")


def rreq(mat, wo_number="WO-1001", **kw):
    """Worked example by default: 100 axial + 2 + 2 = 104 mm blank; 10 x 104 + 10 x 3 = 1070."""
    base = dict(wo_number=wo_number, validated_material_id=mat.id, required_grade="SG450",
                required_section="ROUND", finished_dimension_a_mm=80, finished_axial_length_mm=100,
                machining_stock_a_mm=2, machining_stock_b_mm=2, planned_blanks=10, planned_cuts=10,
                kerf_mm=3, end_trim_mm=0)
    base.update(kw)
    return CCRoutingCreate(**base)


def raw_rreq(mat, wo_number="WO-1001", cls=CCRoutingCreate, **kw):
    """Bypasses schema validation to exercise the service's own checks."""
    base = dict(wo_number=wo_number, validated_material_id=mat.id, required_grade="SG450",
                required_section="ROUND", finished_dimension_a_mm=80, finished_dimension_b_mm=None,
                finished_axial_length_mm=100, machining_stock_a_mm=2, machining_stock_b_mm=2,
                planned_blanks=10, planned_cuts=10, kerf_mm=3, end_trim_mm=0)
    base.update(kw)
    return cls.model_construct(**base)


def sreq(mat, reason="design change", wo_number="WO-1001", **kw):
    base = dict(wo_number=wo_number, validated_material_id=mat.id, required_grade="SG450",
                required_section="ROUND", finished_dimension_a_mm=80, finished_axial_length_mm=100,
                machining_stock_a_mm=2, machining_stock_b_mm=2, planned_blanks=10, planned_cuts=10,
                kerf_mm=3, end_trim_mm=0, reason=reason)
    base.update(kw)
    return CCRoutingSupersede(**base)


def accepted_units(db, store, mat, lengths, accept=True):
    """Post a real inward, then (simulating the existing QA process) accept it."""
    r = InwardSvc.create_inward(db, CCInwardCreate(material_id=mat.id, unit_lengths_mm=lengths), store)
    inward = db.query(cc.ContinuousCastingInward).filter_by(inward_number=r.inward_number).one()
    if accept:
        inward.qa_status = "ACCEPTED"
        db.commit()
    return [db.query(cc.ContinuousCastingStockUnit).filter_by(unit_number=u.unit_number).one() for u in r.units]


def areq(routing_id, unit, planned):
    return CCAllocationCreate(routing_id=routing_id, stock_unit_id=unit.id, planned_length_mm=planned)


def new_routing(db, engineer, mat, wo_number="WO-1001", **kw):
    return RouteSvc.create_routing(db, rreq(mat, wo_number, **kw), engineer)


def count(db, table):
    return db.execute(select(func.count()).select_from(Base.metadata.tables[table])).scalar()


def oms_state(db):
    out = {}
    for t in OMS_TABLES:
        tbl = Base.metadata.tables[t]
        out[t] = sorted((tuple(r) for r in db.execute(select(tbl)).all()), key=repr)
    return out


def unit_state(db):
    tbl = Base.metadata.tables["cc_stock_units"]
    return sorted((tuple(r) for r in db.execute(select(tbl)).all()), key=repr)


def china_counts(db):
    return {t: count(db, t) for t in ["cc_routings", "cc_allocations", "cc_stock_ledger",
                                      "cc_stock_units", "cc_inwards", "audit_logs"]}


# ------------------------------------------------------------------ integer-mm calculations
def test_worked_example_10_by_104_plus_10_by_3_is_1070():
    blank = calculate_blank_length_mm(100, 2, 2)
    assert blank == 104
    gross = calculate_gross_required_length_mm(10, blank, 10, 3, 0)
    assert gross == 10 * 104 + 10 * 3 == 1070
    assert type(blank) is int and type(gross) is int            # never float


@pytest.mark.parametrize("axial,a,b,expected", [(100, 2, 2, 104), (100, 1, 3, 104), (100, 0, 0, 100),
                                                 (1, 0, 0, 1), (250, 5, 7, 262)])
def test_blank_length_calculation(axial, a, b, expected):
    assert calculate_blank_length_mm(axial, a, b) == expected


@pytest.mark.parametrize("blanks,blank,cuts,kerf,trim,expected", [
    (10, 104, 10, 3, 0, 1070), (10, 104, 10, 3, 25, 1095), (1, 100, 0, 0, 0, 100),
    (7, 123_456_789, 0, 0, 0, 864_197_523), (10, 104, 11, 3, 0, 1073), (3, 50, 3, 0, 10, 160),
])
def test_gross_required_length_calculation(blanks, blank, cuts, kerf, trim, expected):
    got = calculate_gross_required_length_mm(blanks, blank, cuts, kerf, trim)
    assert got == expected and type(got) is int


@pytest.mark.parametrize("bad", [10.0, 10.5, "10", None, True, -1])
def test_calculations_reject_floats_bools_and_negatives(bad):
    with pytest.raises(ValueError):
        calculate_blank_length_mm(100, bad, 2)
    with pytest.raises(ValueError):
        calculate_gross_required_length_mm(10, 104, bad, 3, 0)


def test_calculations_reject_zero_axial_length_and_zero_blanks():
    with pytest.raises(ValueError):
        calculate_blank_length_mm(0, 2, 2)
    with pytest.raises(ValueError):
        calculate_gross_required_length_mm(0, 104, 10, 3, 0)


# ------------------------------------------------------------------ routing: creation
def test_valid_cc_routing_on_an_existing_work_order(db, engineer, mat, wo1):
    r = new_routing(db, engineer, mat)
    assert r.version == 1 and r.status == "ACTIVE" and r.material_source == "CONTINUOUS_CASTING"
    assert r.wo_number == "WO-1001" and r.validated_material_code == "M1"
    assert (r.blank_length_mm, r.gross_required_length_mm) == (104, 1070)
    row = db.query(cc.ContinuousCastingRouting).one()
    assert row.work_order_id == wo1.id and row.validated_material_id == mat.id
    assert (row.required_grade, row.required_section) == ("SG450", "ROUND")
    assert (row.finished_axial_length_mm, row.machining_stock_a_mm, row.machining_stock_b_mm) == (100, 2, 2)
    assert (row.planned_blanks, row.planned_cuts, row.kerf_mm, row.end_trim_mm) == (10, 10, 3, 0)
    assert (row.blank_length_mm, row.gross_required_length_mm) == (104, 1070)
    assert row.validated_by == engineer.full_name and row.validated_at is not None
    assert row.created_by == engineer.full_name and row.superseded_at is None
    audit = db.query(AuditLog).filter(AuditLog.action == "CC_ROUTING_CREATED").one()
    assert audit.entity_id == "WO-1001" and audit.user_id == engineer.id


def test_first_routing_is_version_1_and_integers_only(db, engineer, mat, wo1):
    new_routing(db, engineer, mat)
    row = db.query(cc.ContinuousCastingRouting).one()
    assert row.version == 1
    for name in ("blank_length_mm", "gross_required_length_mm", "planned_blanks", "planned_cuts",
                 "kerf_mm", "end_trim_mm", "finished_axial_length_mm"):
        assert type(getattr(row, name)) is int


def test_end_trim_is_part_of_the_gross_requirement(db, engineer, mat, wo1):
    r = new_routing(db, engineer, mat, end_trim_mm=25, finished_dimension_b_mm=30)
    assert r.gross_required_length_mm == 1095
    assert db.query(cc.ContinuousCastingRouting).one().finished_dimension_b_mm == 30


def test_derived_lengths_cannot_be_supplied(mat):
    with pytest.raises(ValidationError):
        rreq(mat, blank_length_mm=999)
    with pytest.raises(ValidationError):
        rreq(mat, gross_required_length_mm=999)


def test_duplicate_work_order_and_version_is_rejected_by_the_database(db, engineer, mat, wo1):
    new_routing(db, engineer, mat)
    db.add(cc.ContinuousCastingRouting(work_order_id=wo1.id, version=1, material_source="CONTINUOUS_CASTING",
                                       status="SUPERSEDED", required_grade="G", required_section="R",
                                       blank_length_mm=1, planned_blanks=1, gross_required_length_mm=1))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_second_active_routing_is_rejected_by_the_service(db, engineer, mat, wo1):
    new_routing(db, engineer, mat)
    before = china_counts(db)
    with pytest.raises(HTTPException) as e:
        new_routing(db, engineer, mat)
    assert e.value.status_code == 409 and "supersede" in e.value.detail
    assert china_counts(db) == before


def test_second_active_routing_is_rejected_by_the_database_too(db, engineer, mat, wo1):
    new_routing(db, engineer, mat)
    db.add(cc.ContinuousCastingRouting(work_order_id=wo1.id, version=2, material_source="CONTINUOUS_CASTING",
                                       status="ACTIVE", required_grade="G", required_section="R",
                                       blank_length_mm=1, planned_blanks=1, gross_required_length_mm=1))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ------------------------------------------------------------------ routing: supersession
def test_superseding_creates_the_next_version_and_marks_the_old_one(db, engineer, mat, wo1):
    new_routing(db, engineer, mat)
    r2 = RouteSvc.supersede_routing(db, sreq(mat, reason="blank length changed", planned_blanks=12), engineer)
    assert r2.version == 2 and r2.status == "ACTIVE" and r2.superseded_version == 1
    assert r2.gross_required_length_mm == 12 * 104 + 10 * 3
    rows = {r.version: r for r in db.query(cc.ContinuousCastingRouting).all()}
    assert rows[1].status == "SUPERSEDED" and rows[2].status == "ACTIVE"
    assert rows[1].superseded_by == engineer.full_name and rows[1].superseded_at is not None
    assert rows[1].supersede_reason == "blank length changed"
    assert sum(1 for r in rows.values() if r.status == "ACTIVE") == 1
    audit = db.query(AuditLog).filter(AuditLog.action == "CC_ROUTING_SUPERSEDED").one()
    assert (audit.old_value, audit.details) == ("v1", "blank length changed")


def test_the_superseded_routings_own_values_are_not_edited(db, engineer, mat, wo1):
    new_routing(db, engineer, mat)
    old = db.query(cc.ContinuousCastingRouting).one()
    keep = ("version", "planned_blanks", "blank_length_mm", "gross_required_length_mm", "kerf_mm",
            "planned_cuts", "end_trim_mm", "finished_axial_length_mm", "machining_stock_a_mm",
            "machining_stock_b_mm", "required_grade", "required_section", "validated_material_id", "created_by")
    before = {k: getattr(old, k) for k in keep}
    RouteSvc.supersede_routing(db, sreq(mat, planned_blanks=99, kerf_mm=9), engineer)
    old = db.query(cc.ContinuousCastingRouting).filter_by(version=1).one()
    assert {k: getattr(old, k) for k in keep} == before


def test_supersession_leaves_historical_allocations_untouched(db, engineer, planner, store, mat, wo1):
    r1 = new_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    AllocSvc.create_allocation(db, areq(uuid.UUID(r1.routing_id), u, 400), planner)
    alloc_before = db.execute(select(Base.metadata.tables["cc_allocations"])).all()
    units_before = unit_state(db)
    RouteSvc.supersede_routing(db, sreq(mat), engineer)
    assert db.execute(select(Base.metadata.tables["cc_allocations"])).all() == alloc_before
    assert unit_state(db) == units_before                       # nothing released or reserved here
    assert count(db, "cc_stock_ledger") == 1                    # only the original INWARD row


def test_supersede_without_an_active_routing_is_404(db, engineer, mat, wo1):
    with pytest.raises(HTTPException) as e:
        RouteSvc.supersede_routing(db, sreq(mat), engineer)
    assert e.value.status_code == 404


def test_supersede_requires_a_reason(db, engineer, mat, wo1):
    new_routing(db, engineer, mat)
    with pytest.raises(ValidationError):
        sreq(mat, reason="")
    with pytest.raises(HTTPException) as e:
        RouteSvc.supersede_routing(db, raw_rreq(mat, cls=CCRoutingSupersede, reason="   "), engineer)
    assert e.value.status_code == 400
    assert db.query(cc.ContinuousCastingRouting).one().status == "ACTIVE"


def test_repeated_supersession_keeps_incrementing_versions(db, engineer, mat, wo1):
    new_routing(db, engineer, mat)
    RouteSvc.supersede_routing(db, sreq(mat), engineer)
    r3 = RouteSvc.supersede_routing(db, sreq(mat), engineer)
    assert r3.version == 3 and r3.superseded_version == 2
    assert sorted(r.version for r in db.query(cc.ContinuousCastingRouting).all()) == [1, 2, 3]
    assert [r.status for r in db.query(cc.ContinuousCastingRouting).order_by(cc.ContinuousCastingRouting.version)] \
        == ["SUPERSEDED", "SUPERSEDED", "ACTIVE"]


def test_versions_are_per_work_order(db, engineer, mat, wo1, wo2):
    new_routing(db, engineer, mat, "WO-1001")
    r = new_routing(db, engineer, mat, "WO-1002")
    assert r.version == 1


# ------------------------------------------------------------------ F1 production flow unaffected
def test_work_orders_without_a_cc_routing_are_unaffected(db, engineer, mat, wo1, wo2):
    before = oms_state(db)
    new_routing(db, engineer, mat, "WO-1001")                    # WO-1002 keeps the normal F1 flow
    assert oms_state(db) == before
    other = db.query(WorkOrder).filter_by(wo_number="WO-1002").one()
    assert db.query(cc.ContinuousCastingRouting).filter_by(work_order_id=other.id).count() == 0


def test_an_f1_production_routing_coexists_but_is_not_a_cc_routing(db, engineer, planner, store, mat, wo1, wo2):
    f1 = cc.ContinuousCastingRouting(work_order_id=wo2.id, version=1, material_source="F1_PRODUCTION",
                                     status="ACTIVE")
    db.add(f1)
    db.commit()
    new_routing(db, engineer, mat, "WO-1001")
    assert db.query(cc.ContinuousCastingRouting).filter_by(material_source="F1_PRODUCTION").one().version == 1
    (u,) = accepted_units(db, store, mat, [1000])
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(f1.id, u, 100), planner)
    assert e.value.status_code == 400 and "CONTINUOUS_CASTING" in e.value.detail
    with pytest.raises(HTTPException) as e:                      # the one-ACTIVE rule spans both sources
        new_routing(db, engineer, mat, "WO-1002")
    assert e.value.status_code == 409


# ------------------------------------------------------------------ routing: validation / roles
@pytest.mark.parametrize("field", ["required_grade", "required_section", "finished_dimension_a_mm",
                                   "finished_axial_length_mm", "machining_stock_a_mm", "machining_stock_b_mm",
                                   "planned_blanks", "planned_cuts", "kerf_mm", "end_trim_mm",
                                   "validated_material_id", "wo_number"])
def test_required_fields_are_enforced_by_the_schema(mat, field):
    data = dict(wo_number="WO-1001", validated_material_id=mat.id, required_grade="G", required_section="R",
                finished_dimension_a_mm=80, finished_axial_length_mm=100, machining_stock_a_mm=2,
                machining_stock_b_mm=2, planned_blanks=10, planned_cuts=10, kerf_mm=3, end_trim_mm=0)
    del data[field]
    with pytest.raises(ValidationError):
        CCRoutingCreate(**data)


@pytest.mark.parametrize("field", ["required_grade", "required_section", "finished_dimension_a_mm",
                                   "finished_axial_length_mm", "machining_stock_a_mm", "machining_stock_b_mm",
                                   "planned_blanks", "planned_cuts", "kerf_mm", "end_trim_mm",
                                   "validated_material_id", "wo_number"])
def test_required_fields_are_enforced_by_the_service_too(db, engineer, mat, wo1, field):
    before = china_counts(db)
    with pytest.raises(HTTPException) as e:
        RouteSvc.create_routing(db, raw_rreq(mat, **{field: None}), engineer)
    assert e.value.status_code == 400
    assert china_counts(db) == before


@pytest.mark.parametrize("kw", [dict(planned_blanks=0), dict(finished_axial_length_mm=0), dict(kerf_mm=-1),
                                dict(machining_stock_a_mm=-1), dict(end_trim_mm=-5), dict(planned_cuts=-1),
                                dict(finished_dimension_a_mm=0), dict(finished_dimension_b_mm=0),
                                dict(kerf_mm=1.5), dict(planned_blanks=2_147_483_648)])
def test_schema_rejects_bad_numbers(mat, kw):
    with pytest.raises(ValidationError):
        rreq(mat, **kw)


@pytest.mark.parametrize("kw", [dict(planned_blanks=0), dict(finished_axial_length_mm=0), dict(kerf_mm=-1),
                                dict(machining_stock_b_mm=-1), dict(kerf_mm=2.5), dict(planned_blanks=True),
                                dict(finished_dimension_a_mm=0), dict(finished_dimension_b_mm=-3)])
def test_service_rejects_bad_numbers_too(db, engineer, mat, wo1, kw):
    with pytest.raises(HTTPException) as e:
        RouteSvc.create_routing(db, raw_rreq(mat, **kw), engineer)
    assert e.value.status_code == 400 and count(db, "cc_routings") == 0


def test_gross_beyond_the_32_bit_column_is_rejected(db, engineer, mat, wo1):
    with pytest.raises(HTTPException) as e:
        RouteSvc.create_routing(db, raw_rreq(mat, planned_blanks=2_000_000_000, finished_axial_length_mm=5), engineer)
    assert e.value.status_code == 400 and count(db, "cc_routings") == 0


def test_unknown_work_order_is_404_and_creates_nothing(db, engineer, mat):
    before = china_counts(db)
    with pytest.raises(HTTPException) as e:
        new_routing(db, engineer, mat, "WO-NOPE")
    assert e.value.status_code == 404 and china_counts(db) == before
    assert count(db, "work_orders") == 0 and count(db, "orders") == 0     # no WO/Order invented


@pytest.mark.parametrize("state", [WOStatus.CLOSED, WOStatus.DISPATCHED])
def test_closed_or_dispatched_work_orders_cannot_take_a_routing(db, engineer, mat, state):
    make_wo(db, "WO-X", status=state)
    with pytest.raises(HTTPException) as e:
        new_routing(db, engineer, mat, "WO-X")
    assert e.value.status_code == 400 and count(db, "cc_routings") == 0


def test_unknown_or_inactive_validated_material(db, engineer, mat, wo1):
    with pytest.raises(HTTPException) as e:
        RouteSvc.create_routing(db, rreq(mat, validated_material_id=uuid.uuid4()), engineer)
    assert e.value.status_code == 404
    mat.is_active = False
    db.commit()
    with pytest.raises(HTTPException) as e:
        new_routing(db, engineer, mat)
    assert e.value.status_code == 400 and count(db, "cc_routings") == 0


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.ENGINEERING])
def test_routing_roles_allowed(db, mat, wo1, role):
    assert new_routing(db, _user(db, role), mat).success


@pytest.mark.parametrize("role", [UserRole.PLANNER, UserRole.STORE, UserRole.QA, UserRole.PRODUCTION_MANAGER,
                                  UserRole.DISPATCH, UserRole.CEO, UserRole.MANUFACTURING])
def test_routing_roles_rejected(db, mat, wo1, role):
    before = china_counts(db)
    with pytest.raises(HTTPException) as e:
        new_routing(db, _user(db, role), mat)
    assert e.value.status_code == 403 and china_counts(db) == before


def test_supersede_roles_and_anonymous(db, engineer, planner, mat, wo1):
    new_routing(db, engineer, mat)
    for user in (planner, None):
        with pytest.raises(HTTPException) as e:
            RouteSvc.supersede_routing(db, sreq(mat), user)
        assert e.value.status_code == 403
    assert db.query(cc.ContinuousCastingRouting).one().status == "ACTIVE"
    with pytest.raises(HTTPException) as e:
        RouteSvc.create_routing(db, rreq(mat), None)
    assert e.value.status_code == 403


# ------------------------------------------------------------------ allocation: eligibility
def _active_routing(db, engineer, mat, wo="WO-1001"):
    return uuid.UUID(new_routing(db, engineer, mat, wo).routing_id)


def test_accepted_stock_allocates(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    a = AllocSvc.create_allocation(db, areq(rid, u, 642), planner)
    assert a.allocation_number == "ALC-000001" and a.status == "PLANNED"
    assert a.planned_length_mm == 642 and a.wo_number == "WO-1001" and a.routing_version == 1
    assert a.stock_unit_number == u.unit_number and a.inward_number == "INW-000001"
    assert a.reserved_length_mm == 0 and a.unit_free_length_mm == 1000
    assert a.unit_available_for_planning_mm == 1000 - 642
    assert (a.routing_gross_required_length_mm, a.routing_planned_total_mm) == (1070, 642)
    row = db.query(cc.ContinuousCastingAllocation).one()
    assert (row.planned_length_mm, row.reserved_length_mm, row.issued_length_mm, row.consumed_length_mm) == (642, 0, 0, 0)
    assert row.status == "PLANNED" and str(row.routing_id) == str(rid) and row.stock_unit_id == u.id
    assert db.query(AuditLog).filter(AuditLog.action == "CC_ALLOCATION_CREATED").one().entity_id == "ALC-000001"


def test_pending_qa_stock_is_rejected(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000], accept=False)
    before = china_counts(db)
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    assert e.value.status_code == 400 and "PENDING_QA" in e.value.detail and "ACCEPTED" in e.value.detail
    assert china_counts(db) == before


@pytest.mark.parametrize("qa", ["REJECTED", "ON_HOLD"])
def test_other_non_accepted_qa_states_are_rejected(db, engineer, planner, store, mat, wo1, qa):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    db.query(cc.ContinuousCastingInward).one().qa_status = qa
    db.commit()
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    assert e.value.status_code == 400 and qa in e.value.detail


@pytest.mark.parametrize("state", ["ON_HOLD", "SCRAPPED", "CONSUMED"])
def test_unit_that_is_not_in_stock_is_rejected(db, engineer, planner, store, mat, wo1, state):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    u.status = state
    db.commit()
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    assert e.value.status_code == 400 and state in e.value.detail and "IN_STOCK" in e.value.detail


def test_insufficient_free_length_is_rejected(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 1001), planner)
    assert e.value.status_code == 400 and "1000" in e.value.detail
    assert AllocSvc.create_allocation(db, areq(rid, u, 1000), planner).success       # exactly all of it is fine


def test_reserved_and_issued_length_reduce_what_can_be_planned(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    u.reserved_length_mm, u.issued_length_mm = 600, 300          # 100 mm physically free
    db.commit()
    with pytest.raises(HTTPException):
        AllocSvc.create_allocation(db, areq(rid, u, 101), planner)
    assert AllocSvc.create_allocation(db, areq(rid, u, 100), planner).success


def test_fully_committed_unit_is_rejected(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    u.reserved_length_mm = 1000
    db.commit()
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 1), planner)
    assert e.value.status_code == 400 and "no free length" in e.value.detail


def test_stock_of_another_material_is_rejected(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    other = _material(db, "M2")
    (u,) = accepted_units(db, store, other, [1000])
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    assert e.value.status_code == 400 and "validated" in e.value.detail


def test_planned_length_must_be_positive(planner, mat):
    with pytest.raises(ValidationError):
        CCAllocationCreate(routing_id=uuid.uuid4(), stock_unit_id=uuid.uuid4(), planned_length_mm=0)
    with pytest.raises(ValidationError):
        CCAllocationCreate(routing_id=uuid.uuid4(), stock_unit_id=uuid.uuid4(), planned_length_mm=-5)
    with pytest.raises(ValidationError):
        CCAllocationCreate(routing_id=uuid.uuid4(), stock_unit_id=uuid.uuid4(), planned_length_mm=1.5)


@pytest.mark.parametrize("bad", [0, -1, True])
def test_service_rejects_non_positive_planned_length(db, engineer, planner, store, mat, wo1, bad):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    raw = CCAllocationCreate.model_construct(routing_id=rid, stock_unit_id=u.id, planned_length_mm=bad)
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, raw, planner)
    assert e.value.status_code == 400 and count(db, "cc_allocations") == 0


def test_unknown_routing_or_unit(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, CCAllocationCreate(routing_id=uuid.uuid4(), stock_unit_id=u.id,
                                                          planned_length_mm=10), planner)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, CCAllocationCreate(routing_id=rid, stock_unit_id=uuid.uuid4(),
                                                          planned_length_mm=10), planner)
    assert e.value.status_code == 404


def test_cannot_allocate_to_a_superseded_routing(db, engineer, planner, store, mat, wo1):
    old = _active_routing(db, engineer, mat)
    RouteSvc.supersede_routing(db, sreq(mat), engineer)
    (u,) = accepted_units(db, store, mat, [1000])
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(old, u, 100), planner)
    assert e.value.status_code == 400 and "SUPERSEDED" in e.value.detail


@pytest.mark.parametrize("state", [WOStatus.CLOSED, WOStatus.DISPATCHED])
def test_cannot_allocate_once_the_work_order_is_closed(db, engineer, planner, store, mat, wo1, state):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    wo1.status = state
    db.commit()
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    assert e.value.status_code == 400 and count(db, "cc_allocations") == 0


# ------------------------------------------------------------------ allocation: many-to-many
def test_one_work_order_draws_from_several_stock_units_and_inwards(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u1,) = accepted_units(db, store, mat, [1000])                  # INW-000001
    u2, u3 = accepted_units(db, store, mat, [900, 800])             # INW-000002
    for u, n in ((u1, 642), (u2, 428), (u3, 100)):
        AllocSvc.create_allocation(db, areq(rid, u, n), planner)
    rows = db.query(cc.ContinuousCastingAllocation).all()
    assert len(rows) == 3 and {r.stock_unit_id for r in rows} == {u1.id, u2.id, u3.id}
    inwards = {db.get(cc.ContinuousCastingStockUnit, r.stock_unit_id).inward_id for r in rows}
    assert len(inwards) == 2                                          # more than one inward feeds one WO
    assert sum(r.planned_length_mm for r in rows) == 1170


def test_one_stock_unit_and_inward_supply_several_work_orders(db, engineer, planner, store, mat, wo1, wo2):
    r1, r2 = _active_routing(db, engineer, mat, "WO-1001"), _active_routing(db, engineer, mat, "WO-1002")
    u1, u2 = accepted_units(db, store, mat, [1000, 1000])           # one inward, two bars
    AllocSvc.create_allocation(db, areq(r1, u1, 600), planner)
    AllocSvc.create_allocation(db, areq(r2, u1, 400), planner)       # same unit, second WO
    AllocSvc.create_allocation(db, areq(r2, u2, 900), planner)       # same inward, other unit
    wos = {(a.routing_id, a.stock_unit_id) for a in db.query(cc.ContinuousCastingAllocation).all()}
    assert len(wos) == 3
    per_unit = {u1.id: 2, u2.id: 1}
    for uid, n in per_unit.items():
        assert db.query(cc.ContinuousCastingAllocation).filter_by(stock_unit_id=uid).count() == n


def test_plans_cannot_oversubscribe_a_unit_across_work_orders(db, engineer, planner, store, mat, wo1, wo2):
    r1, r2 = _active_routing(db, engineer, mat, "WO-1001"), _active_routing(db, engineer, mat, "WO-1002")
    (u,) = accepted_units(db, store, mat, [1000])
    AllocSvc.create_allocation(db, areq(r1, u, 600), planner)
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(r2, u, 401), planner)    # only 400 mm is still plannable
    assert e.value.status_code == 400 and "400" in e.value.detail
    assert AllocSvc.create_allocation(db, areq(r2, u, 400), planner).unit_available_for_planning_mm == 0


def test_a_superseded_routings_unreserved_plan_stops_blocking_the_stock(db, engineer, planner, store, mat, wo1):
    old = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    AllocSvc.create_allocation(db, areq(old, u, 1000), planner)
    new = uuid.UUID(RouteSvc.supersede_routing(db, sreq(mat), engineer).routing_id)
    assert AllocSvc.create_allocation(db, areq(new, u, 1000), planner).success   # old plan was never reserved


def test_a_superseded_routings_reserved_length_still_blocks_the_stock(db, engineer, planner, store, mat, wo1):
    old = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    AllocSvc.create_allocation(db, areq(old, u, 600), planner)
    alloc = db.query(cc.ContinuousCastingAllocation).one()           # simulate a later RESERVE of 600
    alloc.reserved_length_mm, alloc.status = 600, "RESERVED"
    u.reserved_length_mm = 600
    db.commit()
    new = uuid.UUID(RouteSvc.supersede_routing(db, sreq(mat), engineer).routing_id)
    with pytest.raises(HTTPException):
        AllocSvc.create_allocation(db, areq(new, u, 401), planner)
    assert AllocSvc.create_allocation(db, areq(new, u, 400), planner).success


# ------------------------------------------------------------------ allocation: duplicates, roles, numbers
def test_duplicate_routing_and_stock_unit_is_rejected(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    assert e.value.status_code == 409 and count(db, "cc_allocations") == 1


def test_duplicate_routing_and_stock_unit_is_rejected_by_the_database(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    db.add(cc.ContinuousCastingAllocation(allocation_number="ALC-000099", routing_id=rid, stock_unit_id=u.id))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.PLANNER])
def test_allocation_roles_allowed(db, engineer, store, mat, wo1, role):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    assert AllocSvc.create_allocation(db, areq(rid, u, 100), _user(db, role)).success


@pytest.mark.parametrize("role", [UserRole.STORE, UserRole.ENGINEERING, UserRole.PRODUCTION_MANAGER,
                                  UserRole.QA, UserRole.DISPATCH, UserRole.CEO])
def test_allocation_roles_rejected(db, engineer, store, mat, wo1, role):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    before = china_counts(db)
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 100), _user(db, role))
    assert e.value.status_code == 403 and china_counts(db) == before


def test_anonymous_allocation_is_rejected(db, engineer, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 100), None)
    assert e.value.status_code == 403


def test_allocation_numbers_are_sequential(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    u1, u2 = accepted_units(db, store, mat, [1000, 1000])
    assert AllocSvc.create_allocation(db, areq(rid, u1, 10), planner).allocation_number == "ALC-000001"
    assert AllocSvc.create_allocation(db, areq(rid, u2, 10), planner).allocation_number == "ALC-000002"


def _flaky(monkeypatch, first_values):
    real = rsvc.next_cc_allocation_number
    calls = []

    def fake(db):
        calls.append(1)
        return first_values[len(calls) - 1] if len(calls) <= len(first_values) else real(db)

    monkeypatch.setattr(rsvc, "next_cc_allocation_number", fake)
    return calls


def test_allocation_number_collision_is_retried(db, engineer, planner, store, mat, wo1, monkeypatch):
    rid = _active_routing(db, engineer, mat)
    u1, u2 = accepted_units(db, store, mat, [1000, 1000])
    AllocSvc.create_allocation(db, areq(rid, u1, 10), planner)
    calls = _flaky(monkeypatch, ["ALC-000001"])
    a = AllocSvc.create_allocation(db, areq(rid, u2, 10), planner)
    assert len(calls) == 2 and a.allocation_number == "ALC-000002" and count(db, "cc_allocations") == 2


def test_persistent_allocation_number_collision_is_a_controlled_409(db, engineer, planner, store, mat, wo1, monkeypatch):
    rid = _active_routing(db, engineer, mat)
    u1, u2 = accepted_units(db, store, mat, [1000, 1000])
    AllocSvc.create_allocation(db, areq(rid, u1, 10), planner)
    before = china_counts(db)
    calls = _flaky(monkeypatch, ["ALC-000001"] * 10)
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u2, 10), planner)
    assert e.value.status_code == 409 and len(calls) == rsvc.CC_NUMBER_MAX_ATTEMPTS
    assert china_counts(db) == before


def test_a_concurrent_duplicate_pair_is_a_409_not_a_retry(db, engineer, planner, store, mat, wo1, monkeypatch):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    calls = []

    def raced(*a, **k):
        calls.append(1)
        raise IntegrityError("stmt", {}, Exception(
            "UNIQUE constraint failed: cc_allocations.routing_id, cc_allocations.stock_unit_id"))

    monkeypatch.setattr(rsvc, "_post_allocation", raced)
    with pytest.raises(HTTPException) as e:
        AllocSvc.create_allocation(db, areq(rid, u, 10), planner)
    assert e.value.status_code == 409 and len(calls) == 1


# ------------------------------------------------------------------ allocation plans only
def test_allocation_does_not_change_any_stock_balance(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    u1, u2 = accepted_units(db, store, mat, [1000, 1500])
    before = unit_state(db)
    AllocSvc.create_allocation(db, areq(rid, u1, 642), planner)
    AllocSvc.create_allocation(db, areq(rid, u2, 428), planner)
    assert unit_state(db) == before                       # reserved/issued/remaining/consumed untouched
    for u in db.query(cc.ContinuousCastingStockUnit).all():
        assert (u.reserved_length_mm, u.issued_length_mm, u.consumed_length_mm) == (0, 0, 0)
        assert u.remaining_length_mm == u.original_length_mm


def test_allocation_creates_no_ledger_rows(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    ledger_before = db.execute(select(Base.metadata.tables["cc_stock_ledger"])).all()
    AllocSvc.create_allocation(db, areq(rid, u, 400), planner)
    assert db.execute(select(Base.metadata.tables["cc_stock_ledger"])).all() == ledger_before
    assert {t for (t,) in db.query(cc.ContinuousCastingStockLedger.movement_type).all()} == {"INWARD"}


def test_routing_and_allocation_leave_the_existing_oms_work_order_unchanged(db, engineer, planner, store, mat, wo1):
    (u,) = accepted_units(db, store, mat, [1000])
    before = oms_state(db)
    rid = _active_routing(db, engineer, mat)
    AllocSvc.create_allocation(db, areq(rid, u, 400), planner)
    RouteSvc.supersede_routing(db, sreq(mat, planned_blanks=11), engineer)
    assert oms_state(db) == before                                  # WO, routes, StageWIP, movements: identical rows


def test_no_order_or_work_order_is_ever_created(db, engineer, planner, store, mat, wo1):
    orders, wos = count(db, "orders"), count(db, "work_orders")
    (u,) = accepted_units(db, store, mat, [1000])
    rid = _active_routing(db, engineer, mat)
    AllocSvc.create_allocation(db, areq(rid, u, 400), planner)
    RouteSvc.supersede_routing(db, sreq(mat), engineer)
    assert (count(db, "orders"), count(db, "work_orders")) == (orders, wos) == (1, 1)
    assert count(db, "wo_routes") == 3 and count(db, "stage_wips") == 1       # the OMS route is not touched


# ------------------------------------------------------------------ locking
def test_allocation_locks_the_stock_unit_before_validating(db, engineer, planner, store, mat, wo1, monkeypatch):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    locked = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        locked.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    assert cc.ContinuousCastingStockUnit in locked


def test_supersession_locks_the_existing_routings(db, engineer, mat, wo1, monkeypatch):
    new_routing(db, engineer, mat)
    locked = []
    real = Query.with_for_update

    def spy(self, *a, **k):
        locked.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    RouteSvc.supersede_routing(db, sreq(mat), engineer)
    assert cc.ContinuousCastingRouting in locked


# ------------------------------------------------------------------ transaction rollback
def _boom(*a, **k):
    raise RuntimeError("injected failure")


def test_routing_creation_rolls_back_on_failure(db, engineer, mat, wo1, monkeypatch):
    before = china_counts(db)
    monkeypatch.setattr(rsvc, "AuditLog", _boom)                    # after the routing row is staged
    with pytest.raises(RuntimeError):
        new_routing(db, engineer, mat)
    assert china_counts(db) == before and count(db, "cc_routings") == 0


def test_supersession_rolls_back_the_old_routing_status_too(db, engineer, mat, wo1, monkeypatch):
    new_routing(db, engineer, mat)
    before = china_counts(db)
    monkeypatch.setattr(rsvc, "AuditLog", _boom)                    # after the old routing was marked + flushed
    with pytest.raises(RuntimeError):
        RouteSvc.supersede_routing(db, sreq(mat), engineer)
    monkeypatch.undo()
    old = db.query(cc.ContinuousCastingRouting).one()
    assert old.status == "ACTIVE" and old.superseded_at is None and old.supersede_reason is None
    assert china_counts(db) == before


def test_allocation_rolls_back_on_failure_before_flush(db, engineer, planner, store, mat, wo1, monkeypatch):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    before = china_counts(db)
    monkeypatch.setattr(rsvc, "AuditLog", _boom)
    with pytest.raises(RuntimeError):
        AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    assert china_counts(db) == before


def test_allocation_rolls_back_after_everything_was_flushed(db, engineer, planner, store, mat, wo1, monkeypatch):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000])
    before = china_counts(db)
    seen = {}

    def late(*a, **k):
        seen["flushed"] = db.execute(select(func.count()).select_from(
            Base.metadata.tables["cc_allocations"])).scalar()
        raise RuntimeError("late failure")

    monkeypatch.setattr(rsvc, "CCAllocationResult", late)
    with pytest.raises(RuntimeError):
        AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    assert seen["flushed"] == 1                                     # the row really was in the transaction
    assert china_counts(db) == before


def test_failed_operations_do_not_burn_allocation_numbers(db, engineer, planner, store, mat, wo1):
    rid = _active_routing(db, engineer, mat)
    (u,) = accepted_units(db, store, mat, [1000], accept=False)
    with pytest.raises(HTTPException):
        AllocSvc.create_allocation(db, areq(rid, u, 100), planner)
    u.inward.qa_status = "ACCEPTED"
    db.commit()
    assert AllocSvc.create_allocation(db, areq(rid, u, 100), planner).allocation_number == "ALC-000001"


# ------------------------------------------------------------------ scope guard
def test_service_touches_oms_only_through_a_read_of_workorder():
    src = Path(rsvc.__file__).read_text(encoding="utf-8")
    modules = re.findall(r"^\s*from\s+(\S+)\s+import\s+(.+?)$", src, flags=re.M)
    oms_imports = {m: names for m, names in modules
                   if m.startswith("app.models.") or m.startswith("app.services.")}
    for module in oms_imports:
        assert module not in ("app.services.production_service", "app.services.work_order_service",
                              "app.services.oms_integration_service", "app.services.operations_service",
                              "app.services.rejection_service", "app.models.production_movement",
                              "app.models.production", "app.models.nc", "app.models.order")
    wo_names = {n.strip() for n in oms_imports["app.models.work_order"].split(",")}
    assert wo_names == {"WorkOrder", "WOStatus"}                    # no WORoute / StageWIP / movements
    assert "oms_engine" not in src.replace("oms_engine.py", "")
