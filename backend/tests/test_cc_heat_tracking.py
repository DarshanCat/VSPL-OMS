"""Continuous Casting Phase 3: Heat Number Tracking and Traceability Tests.
Isolated in-memory SQLite only."""
import uuid
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import *  # noqa: F401,F403
from app.models import continuous_casting as cc
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.models.order import Order, Customer, Part, OrderStatus
from app.schemas.continuous_casting import (
    CCInwardCreate,
    CCRoutingCreate,
    CCAllocationCreate,
    CCSplitCreate,
    CCCutConsumeCreate,
    CCCutResultCreate,
    CCHeatReconcileRequest,
)
from app.services.continuous_casting_service import ContinuousCastingInwardService as InwardSvc
from app.services.continuous_casting_routing_service import (
    ContinuousCastingRoutingService as RouteSvc,
    ContinuousCastingAllocationService as AllocSvc,
)
from app.services.continuous_casting_reservation_service import ContinuousCastingReservationService as RsvSvc
from app.services.continuous_casting_split_service import ContinuousCastingSplitService as SplitSvc
from app.services.continuous_casting_cut_service import ContinuousCastingCutService as CutSvc
from app.services.continuous_casting_physical_service import ContinuousCastingPhysicalService as PhysSvc
from app.services.continuous_casting_read_service import ContinuousCastingReadService as ReadSvc


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _user(db, role, name="Test User"):
    email = f"{name.replace(' ', '.').lower()}_{role.value}@example.test"
    u = User(full_name=name, email=email, hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def store_user(db):
    return _user(db, UserRole.STORE, "Store Keeper")


@pytest.fixture()
def qa_user(db):
    return _user(db, UserRole.QA, "QA Inspector")


@pytest.fixture()
def eng_user(db):
    return _user(db, UserRole.ENGINEERING, "Engineer")


@pytest.fixture()
def prod_user(db):
    return _user(db, UserRole.PRODUCTION_MANAGER, "Prod Mgr")


@pytest.fixture()
def planner_user(db):
    return _user(db, UserRole.PLANNER, "Planner")


@pytest.fixture()
def mat(db):
    m = cc.ContinuousCastingMaterial(
        material_code="CC-HEAT-01",
        grade="SG 500/7",
        section="RECTANGLE",
        stock_dimension_a_mm=160,
        stock_dimension_b_mm=205,
    )
    db.add(m)
    db.commit()
    return m


def make_wo(db, number="WO-17535", *, casting_process):
    """casting_process is required, not defaulted: every caller in this file creates a
    real Continuous Casting routing (RouteSvc.create_routing), which the eligibility gate
    (_require_cc_eligible_work_order) checks against casting_process == 'CONTINUOUS'. Making
    the value an explicit, visible choice at each call site -- instead of a hidden default --
    keeps that dependency honest rather than silently papering over it."""
    cust = Customer(customer_code=f"C-{number}", name="Customer 1")
    part = Part(part_number="PMC210", description="Part PMC210")
    db.add_all([cust, part])
    db.flush()
    order = Order(
        oar_number=f"OAR-{number}",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-100",
        po_qty=19,
        max_batch_size=19,
        status=OrderStatus.ACCEPT,
    )
    db.add(order)
    db.flush()
    wo = WorkOrder(
        wo_number=number,
        order_id=order.id,
        physical_wo_qty=19,
        current_stage="F1",
        projected_final_good=19,
        status=WOStatus.IN_PRODUCTION,
        casting_process=casting_process,
    )
    db.add(wo)
    db.flush()
    for seq, stage in enumerate(["F1", "F2", "DISPATCH"], start=1):
        db.add(WORoute(work_order_id=wo.id, stage=stage, sequence=seq, stage_target_qty=19))
    db.add(
        StageWIP(
            work_order_id=wo.id,
            stage="F1",
            ent_qty=19,
            ok_qty=0,
            inproc_qty=19,
            onhand_qty=0,
            rejected_qty=0,
            available_wip=19,
        )
    )
    db.commit()
    return wo


# ------------------------------------------------------------------ Test Cases

def test_inward_requires_heat_number_validation(mat):
    # Missing heat_number
    with pytest.raises(ValidationError):
        CCInwardCreate(material_id=mat.id, unit_lengths_mm=[1000])

    # Empty string heat_number
    with pytest.raises(ValidationError):
        CCInwardCreate(material_id=mat.id, unit_lengths_mm=[1000], heat_number="")

    # Whitespace-only heat_number
    with pytest.raises(ValidationError):
        CCInwardCreate(material_id=mat.id, unit_lengths_mm=[1000], heat_number="   ")


def test_inward_creates_stock_units_with_heat_number(db, store_user, mat):
    req = CCInwardCreate(
        material_id=mat.id,
        unit_lengths_mm=[1000, 1000, 1000],
        heat_number="HT-2026-9901",
        grn_reference="GRN-8812",
        location="Rack-A1",
    )
    res = InwardSvc.create_inward(db, req, store_user)
    assert res.success is True
    assert res.heat_number == "HT-2026-9901"
    assert len(res.units) == 3

    # Check database rows
    inward = db.query(cc.ContinuousCastingInward).filter_by(id=uuid.UUID(res.inward_id)).one()
    assert inward.heat_number == "HT-2026-9901"

    units = db.query(cc.ContinuousCastingStockUnit).filter_by(inward_id=inward.id).all()
    assert len(units) == 3
    for u in units:
        assert u.heat_number == "HT-2026-9901"

    # Check AuditLog
    audit_entry = db.query(AuditLog).filter(
        AuditLog.action == "CC_INWARD",
        AuditLog.entity_id == inward.inward_number,
    ).first()
    assert audit_entry is not None
    assert "HT-2026-9901" in (audit_entry.details or "")


def test_split_inherits_parent_heat_number(db, store_user, mat):
    req = CCInwardCreate(
        material_id=mat.id,
        unit_lengths_mm=[1000],
        heat_number="HT-SPLIT-001",
    )
    res = InwardSvc.create_inward(db, req, store_user)
    parent_unit = db.query(cc.ContinuousCastingStockUnit).filter_by(unit_number=res.units[0].unit_number).one()
    assert parent_unit.heat_number == "HT-SPLIT-001"

    split_req = CCSplitCreate(
        stock_unit_id=parent_unit.id,
        inward_id=parent_unit.inward_id,
        length_mm=400,
        reason="Test split for cutting remnant",
    )
    split_res = SplitSvc.split(db, split_req, store_user)
    assert split_res.success is True

    child_unit = db.query(cc.ContinuousCastingStockUnit).filter_by(id=uuid.UUID(split_res.child_unit_id)).one()
    assert child_unit.parent_unit_id == parent_unit.id
    assert child_unit.heat_number == "HT-SPLIT-001"
    assert child_unit.remaining_length_mm == 400
    assert parent_unit.remaining_length_mm == 600


def test_cut_record_inherits_stock_unit_heat_number(db, store_user, qa_user, eng_user, prod_user, planner_user, mat):
    from app.schemas.continuous_casting import CCReserveCreate, CCIssueCreate
    # 1. Inward with heat number
    inw_res = InwardSvc.create_inward(
        db,
        CCInwardCreate(material_id=mat.id, unit_lengths_mm=[3000], heat_number="HT-CUT-77"),
        store_user,
    )
    inward = db.query(cc.ContinuousCastingInward).filter_by(id=uuid.UUID(inw_res.inward_id)).one()
    inward.qa_status = "ACCEPTED"
    db.commit()

    stock_unit = db.query(cc.ContinuousCastingStockUnit).filter_by(inward_id=inward.id).one()
    assert stock_unit.heat_number == "HT-CUT-77"

    # 2. Work Order & Routing
    wo = make_wo(db, "WO-17535", casting_process="CONTINUOUS")
    r_create = CCRoutingCreate(
        wo_number=wo.wo_number,
        validated_material_id=mat.id,
        required_grade="SG 500/7",
        required_section="RECTANGLE",
        finished_dimension_a_mm=152,
        finished_dimension_b_mm=150,
        finished_axial_length_mm=127,
        machining_stock_a_mm=5,
        machining_stock_b_mm=5,
        planned_blanks=19,
        planned_cuts=19,
        kerf_mm=4,
        end_trim_mm=30,
    )
    r_res = RouteSvc.create_routing(db, r_create, eng_user)

    # 3. Allocation & Reservation & Issue & Cut Consume
    alloc_res = AllocSvc.create_allocation(
        db,
        CCAllocationCreate(routing_id=uuid.UUID(r_res.routing_id), stock_unit_id=stock_unit.id, planned_length_mm=2709),
        planner_user,
    )
    alloc_id = uuid.UUID(alloc_res.allocation_id)

    # Reserve & Issue
    RsvSvc.reserve(
        db,
        CCReserveCreate(routing_id=uuid.UUID(r_res.routing_id), allocation_id=alloc_id, length_mm=2709),
        planner_user,
    )
    RsvSvc.issue(
        db,
        CCIssueCreate(
            routing_id=uuid.UUID(r_res.routing_id),
            allocation_id=alloc_id,
            stock_unit_id=stock_unit.id,
            length_mm=2709,
        ),
        store_user,
    )

    # Cut Consume
    cc_res = RsvSvc.cut_consume(
        db,
        CCCutConsumeCreate(
            routing_id=uuid.UUID(r_res.routing_id),
            allocation_id=alloc_id,
            stock_unit_id=stock_unit.id,
            length_mm=2709,
        ),
        prod_user,
    )

    # 4. Record Cut Result
    cut_req = CCCutResultCreate(
        routing_id=uuid.UUID(r_res.routing_id),
        allocation_id=alloc_id,
        stock_unit_id=stock_unit.id,
        ledger_transaction_number=cc_res.ledger_transaction_number,
        consumed_length_mm=2709,
        actual_good_blanks=19,
        rejected_blanks=0,
        actual_cuts=19,
        end_trim_mm=30,
        remarks="Cuts completed according to routing",
    )
    cut_res = CutSvc.record_cut_result(db, cut_req, prod_user)
    assert cut_res.success is True

    cut_record = db.query(cc.ContinuousCastingCutRecord).filter_by(cut_number=cut_res.cut_number).one()
    assert cut_record.heat_number == "HT-CUT-77"


def test_legacy_unreconciled_heat_and_reconcile_workflow(db, store_user, qa_user, mat):
    # Simulate legacy inward and stock unit with heat_number IS NULL
    legacy_inward = cc.ContinuousCastingInward(
        inward_number="INW-LEGACY-01",
        material_id=mat.id,
        grade=mat.grade,
        section=mat.section,
        stock_dimension_a_mm=mat.stock_dimension_a_mm,
        stock_dimension_b_mm=mat.stock_dimension_b_mm,
        received_piece_count=2,
        received_total_length_mm=2000,
        qa_status="ACCEPTED",
        heat_number=None,  # Legacy NULL
    )
    db.add(legacy_inward)
    db.flush()

    u1 = cc.ContinuousCastingStockUnit(
        unit_number="UNIT-LEGACY-01",
        inward_id=legacy_inward.id,
        original_length_mm=1000,
        remaining_length_mm=1000,
        status="IN_STOCK",
        heat_number=None,
    )
    u2 = cc.ContinuousCastingStockUnit(
        unit_number="UNIT-LEGACY-02",
        inward_id=legacy_inward.id,
        original_length_mm=1000,
        remaining_length_mm=1000,
        status="IN_STOCK",
        heat_number=None,
    )
    db.add_all([u1, u2])
    db.commit()

    # Verify read service outputs None / null heat_number for legacy
    inw_read = ReadSvc.get_inward(db, legacy_inward.id)
    assert inw_read.heat_number is None

    u_read = ReadSvc.get_stock_unit(db, u1.id)
    assert u_read.heat_number is None

    # Reconcile Inward Heat
    rec_req = CCHeatReconcileRequest(
        heat_number="HT-LEGACY-RECONCILED-01",
        reason="Verified against manufacturer test certificate MTC-2026-X",
    )
    rec_res = PhysSvc.reconcile_inward_heat(db, legacy_inward.id, rec_req, qa_user)
    assert rec_res.success is True
    assert rec_res.heat_number == "HT-LEGACY-RECONCILED-01"
    assert rec_res.units_updated == 2

    # Assert database updated
    db.refresh(legacy_inward)
    db.refresh(u1)
    db.refresh(u2)
    assert legacy_inward.heat_number == "HT-LEGACY-RECONCILED-01"
    assert u1.heat_number == "HT-LEGACY-RECONCILED-01"
    assert u2.heat_number == "HT-LEGACY-RECONCILED-01"

    # Assert AuditLog recorded
    audit_rec = db.query(AuditLog).filter(
        AuditLog.action == "CC_HEAT_RECONCILE",
        AuditLog.entity == "ContinuousCastingInward",
        AuditLog.entity_id == legacy_inward.inward_number,
    ).first()
    assert audit_rec is not None
    assert "heat=HT-LEGACY-RECONCILED-01" in (audit_rec.new_value or "")
    assert "MTC-2026-X" in (audit_rec.details or "")


def test_reconcile_individual_stock_unit_heat(db, store_user, qa_user, mat):
    inward = cc.ContinuousCastingInward(
        inward_number="INW-UNIT-REC",
        material_id=mat.id,
        grade=mat.grade,
        section=mat.section,
        stock_dimension_a_mm=mat.stock_dimension_a_mm,
        stock_dimension_b_mm=mat.stock_dimension_b_mm,
        received_piece_count=1,
        received_total_length_mm=1000,
        qa_status="ACCEPTED",
        heat_number="HT-OLD",
    )
    db.add(inward)
    db.flush()
    unit = cc.ContinuousCastingStockUnit(
        unit_number="UNIT-REC-01",
        inward_id=inward.id,
        original_length_mm=1000,
        remaining_length_mm=1000,
        status="IN_STOCK",
        heat_number="HT-OLD",
    )
    db.add(unit)
    db.commit()

    rec_res = PhysSvc.reconcile_stock_unit_heat(
        db,
        unit.id,
        CCHeatReconcileRequest(heat_number="HT-CORRECTED", reason="Physical stamp on bar verified as HT-CORRECTED"),
        qa_user,
    )
    assert rec_res.success is True
    assert rec_res.heat_number == "HT-CORRECTED"
    assert rec_res.units_updated == 1

    db.refresh(unit)
    assert unit.heat_number == "HT-CORRECTED"


def test_heat_traceability_read_service(db, store_user, qa_user, eng_user, prod_user, planner_user, mat):
    # 1. Inward
    inw_res = InwardSvc.create_inward(
        db,
        CCInwardCreate(material_id=mat.id, unit_lengths_mm=[2000, 2000], heat_number="HT-TRACE-ALPHA"),
        store_user,
    )
    inward = db.query(cc.ContinuousCastingInward).filter_by(id=uuid.UUID(inw_res.inward_id)).one()
    inward.qa_status = "ACCEPTED"
    db.commit()

    units = db.query(cc.ContinuousCastingStockUnit).filter_by(inward_id=inward.id).all()

    # 2. Routing and allocation
    wo = make_wo(db, "WO-TRACE-1", casting_process="CONTINUOUS")
    r_create = CCRoutingCreate(
        wo_number=wo.wo_number,
        validated_material_id=mat.id,
        required_grade="SG 500/7",
        required_section="RECTANGLE",
        finished_dimension_a_mm=152,
        finished_axial_length_mm=127,
        machining_stock_a_mm=5,
        machining_stock_b_mm=5,
        planned_blanks=10,
        planned_cuts=10,
        kerf_mm=4,
        end_trim_mm=0,
    )
    r_res = RouteSvc.create_routing(db, r_create, eng_user)

    alloc_res = AllocSvc.create_allocation(
        db,
        CCAllocationCreate(routing_id=uuid.UUID(r_res.routing_id), stock_unit_id=units[0].id, planned_length_mm=1410),
        planner_user,
    )

    # 3. Call trace_heat
    trace = ReadSvc.trace_heat(db, "HT-TRACE-ALPHA")
    assert trace.heat_number == "HT-TRACE-ALPHA"
    assert len(trace.inwards) == 1
    assert len(trace.stock_units) == 2
    assert trace.units_total == 2
    assert trace.allocations_total == 1
    assert len(trace.work_orders) == 1
    assert trace.work_orders[0].wo_number == "WO-TRACE-1"

    # Querying non-existent heat returns 0 totals
    empty_trace = ReadSvc.trace_heat(db, "NON-EXISTENT-HEAT")
    assert empty_trace.heat_number == "NON-EXISTENT-HEAT"
    assert len(empty_trace.inwards) == 0
    assert len(empty_trace.stock_units) == 0


def test_heat_number_filter_queries(db, store_user, mat):
    InwardSvc.create_inward(db, CCInwardCreate(material_id=mat.id, unit_lengths_mm=[1000], heat_number="HT-FLT-A"), store_user)
    InwardSvc.create_inward(db, CCInwardCreate(material_id=mat.id, unit_lengths_mm=[1000], heat_number="HT-FLT-B"), store_user)

    # Filter inwards by heat_number
    res_a = ReadSvc.list_inwards(db, heat_number="FLT-A")
    assert res_a.total == 1
    assert res_a.items[0].heat_number == "HT-FLT-A"

    # Filter stock units by heat_number
    units_b = ReadSvc.list_stock_units(db, heat_number="FLT-B")
    assert units_b.total == 1
    assert units_b.items[0].heat_number == "HT-FLT-B"

