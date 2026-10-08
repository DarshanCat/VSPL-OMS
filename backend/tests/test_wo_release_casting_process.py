"""Unit and integration tests for Work Order Release with Casting Process Selection (F1: Centrifugal vs Continuous Casting)
and Continuous Casting Production Gate enforcement.
"""
import pytest
import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.models.continuous_casting import (
    ContinuousCastingMaterial,
    ContinuousCastingInward,
    ContinuousCastingRouting,
    ContinuousCastingAllocation,
    ContinuousCastingStockUnit,
    ContinuousCastingStockLedger,
    ContinuousCastingCutRecord,
    MATERIAL_SOURCE_CONTINUOUS_CASTING,
)
from app.schemas.operations import WOReleaseCreate
from app.schemas.production import RecordStageProductionRequest
from app.services.operations_service import OperationsService
from app.services.work_order_service import WorkOrderService
from app.services.production_service import ProductionService
from app.services.continuous_casting_read_service import ContinuousCastingReadService


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth_headers(user: User) -> dict:
    token = create_access_token(
        data={"sub": user.email, "user_id": str(user.id), "role": user.role.value}
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_base_data(db):
    customer = Customer(customer_code="CUST-CC", name="Precision Casting Customer")
    part = Part(part_number="PART-CC-01", grade="SG 500/7", description="Continuous Cast Bearing")
    db.add_all([customer, part])
    db.flush()

    planner = User(
        email="planner.test@vijayspheroidals.com",
        full_name="Planning Lead",
        hashed_password="fakehash",
        role=UserRole.PLANNER,
        is_active=True,
    )
    operator = User(
        email="operator.test@vijayspheroidals.com",
        full_name="Floor Operator",
        hashed_password="fakehash",
        role=UserRole.OPERATOR,
        is_active=True,
    )
    admin = User(
        email="admin.test@vijayspheroidals.com",
        full_name="System Admin",
        hashed_password="fakehash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add_all([planner, operator, admin])
    db.flush()

    order = Order(
        oar_number="OAR-9001",
        customer_id=customer.id,
        part_id=part.id,
        customer_po="PO-CC-9001",
        po_qty=100,
        max_batch_size=100,
        status=OrderStatus.ACCEPT,
    )
    db.add(order)
    db.flush()

    now = datetime.now(timezone.utc)
    wo = WorkOrder(
        wo_number="WO-9001",
        order_id=order.id,
        physical_wo_qty=100,
        current_stage="F1",
        status=WOStatus.PLANNED,
        engineering_released_by="Lead Engineer",
        engineering_released_at=now,
        manufacturing_released_by="Mfg Lead",
        manufacturing_released_at=now,
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    db.refresh(planner)
    db.refresh(operator)
    db.refresh(admin)
    return customer, part, order, wo, planner, operator, admin


# ==============================================================================
# WO RELEASE & ROUTE SEMANTICS TESTS
# ==============================================================================

def test_1_release_wo_with_f1_continuous_casting_route_semantics(client, db_session):
    """TEST 1: Release WO with CONTINUOUS removes F1 from executable WORoute and starts at F2."""
    customer, part, order, wo, planner, _, _ = _seed_base_data(db_session)

    res = client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F1", "F2", "F3", "FI", "PACKING", "DISPATCH"],
            "casting_process": "CONTINUOUS",
            "remarks": "Continuous Casting raw stock release",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["wo_number"] == "WO-9001"
    assert data["released_qty"] == 100
    assert data["casting_process"] == "CONTINUOUS"
    # Route should not contain F1 as an executable stage
    assert "F2 -> F3 -> FI -> PACKING -> DISPATCH" in data["route"]
    assert "F1" not in data["route"]

    # Verify database persistence
    db_wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-9001").first()
    assert db_wo.casting_process == "CONTINUOUS"
    assert db_wo.status == WOStatus.RELEASED
    assert db_wo.current_stage == "F2"

    # Verify WORoute starts at F2 without F1
    routes = db_session.query(WORoute).filter(WORoute.work_order_id == db_wo.id).order_by(WORoute.sequence).all()
    assert [r.stage for r in routes] == ["F2", "F3", "FI", "PACKING", "DISPATCH"]

    # Verify initial StageWIP is at F2
    wips = db_session.query(StageWIP).filter(StageWIP.work_order_id == db_wo.id).all()
    assert len(wips) == 1
    assert wips[0].stage == "F2"
    assert wips[0].available_wip == 100


def test_2_release_wo_with_f1_centrifugal_casting(client, db_session):
    """TEST 2: Release WO with CENTRIFUGAL retains F1 as the starting production stage."""
    customer, part, order, wo, planner, _, _ = _seed_base_data(db_session)

    res = client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"],
            "casting_process": "CENTRIFUGAL",
            "remarks": "Standard Centrifugal Casting Melt",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["casting_process"] == "CENTRIFUGAL"
    assert "F1 -> F2 -> F3 -> SP -> FI -> PACKING -> DISPATCH" in data["route"]

    db_wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-9001").first()
    assert db_wo.casting_process == "CENTRIFUGAL"
    assert db_wo.current_stage == "F1"

    routes = db_session.query(WORoute).filter(WORoute.work_order_id == db_wo.id).order_by(WORoute.sequence).all()
    assert [r.stage for r in routes] == ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]


def test_3_release_wo_with_f1_missing_or_invalid_casting_process(client, db_session):
    """TEST 3: F1 in route defaults omitted casting process to CENTRIFUGAL; rejects invalid."""
    customer, part, order, wo, planner, _, _ = _seed_base_data(db_session)

    # Missing casting process defaults to CENTRIFUGAL
    res1 = client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F1", "F2", "DISPATCH"],
        },
    )
    assert res1.status_code == 200, res1.text
    data1 = res1.json()
    assert data1["success"] is True
    assert data1["casting_process"] == "CENTRIFUGAL"
    assert "F1 -> F2 -> DISPATCH" in data1["route"]

    # Re-plan WO for second test case
    wo.status = WOStatus.PLANNED
    db_session.commit()

    # Invalid casting process
    res2 = client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F1", "F2", "DISPATCH"],
            "casting_process": "SAND_CASTING",
        },
    )
    assert res2.status_code == 400
    assert "Invalid casting process 'SAND_CASTING'" in res2.json()["detail"]



def test_4_release_wo_without_f1(client, db_session):
    """TEST 4: Non-F1 route (e.g. proof turned stock) proceeds directly."""
    customer, part, order, wo, planner, _, _ = _seed_base_data(db_session)

    res = client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F2", "F3", "FI", "PACKING", "DISPATCH"],
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["casting_process"] is None

    db_wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-9001").first()
    assert db_wo.current_stage == "F2"


# ==============================================================================
# CONTINUOUS CASTING EXECUTION GATE TESTS
# ==============================================================================

def test_5_continuous_wo_without_cc_routing_rejected(client, db_session):
    """TEST 5: CONTINUOUS WO with NO active CC routing is rejected at production entry and move."""
    customer, part, order, wo, planner, operator, admin = _seed_base_data(db_session)

    # Release WO as CONTINUOUS
    client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F1", "F2", "F3", "DISPATCH"],
            "casting_process": "CONTINUOUS",
        },
    )

    # Attempt production entry at F2 (first downstream stage)
    res = client.post(
        "/api/v1/production/entry",
        headers=_auth_headers(admin),
        json={
            "wo_number": "WO-9001",
            "stage": "F2",
            "good_qty": 10,
            "rejected_quantity": 0,
            "remarks": "Attempting initial rough turn",
        },
    )
    assert res.status_code == 400
    assert "has no active Continuous Casting routing" in res.json()["detail"]


def test_6_continuous_wo_with_draft_cc_routing_rejected(client, db_session):
    """TEST 6: CONTINUOUS WO with DRAFT CC routing is rejected at production entry."""
    customer, part, order, wo, planner, _, admin = _seed_base_data(db_session)

    client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F1", "F2", "DISPATCH"],
            "casting_process": "CONTINUOUS",
        },
    )

    # Create DRAFT routing
    mat = ContinuousCastingMaterial(
        id=uuid.uuid4(),
        material_code="MAT-SG500-100",
        grade="SG 500/7",
        section="ROUND",
        stock_dimension_a_mm=100,
        is_active=True,
    )
    db_session.add(mat)
    db_session.flush()

    draft_routing = ContinuousCastingRouting(
        id=uuid.uuid4(),
        work_order_id=wo.id,
        version=1,
        material_source=MATERIAL_SOURCE_CONTINUOUS_CASTING,
        status="DRAFT",
        required_grade="SG 500/7",
        required_section="ROUND",
        finished_dimension_a_mm=90,
        finished_axial_length_mm=150,
        planned_blanks=100,
        blank_length_mm=160,
        machining_stock_a_mm=5,
        machining_stock_b_mm=5,
        kerf_mm=4,
        planned_cuts=100,
        end_trim_mm=20,
        gross_required_length_mm=16420,
        validated_material_id=mat.id,
        validated_by="planner",
        created_by="planner",
    )
    db_session.add(draft_routing)
    db_session.commit()

    res = client.post(
        "/api/v1/production/entry",
        headers=_auth_headers(admin),
        json={
            "wo_number": "WO-9001",
            "stage": "F2",
            "good_qty": 10,
            "rejected_quantity": 0,
        },
    )
    assert res.status_code == 400
    assert "has no active Continuous Casting routing" in res.json()["detail"]


def test_7_continuous_wo_attempting_f1_production_rejected(client, db_session):
    """TEST 7: CONTINUOUS WO attempting F1 production is explicitly rejected (CC bypasses F1)."""
    customer, part, order, wo, planner, _, admin = _seed_base_data(db_session)

    # Set WO casting process to CONTINUOUS and add an F1 route stage
    wo.casting_process = "CONTINUOUS"
    wo.status = WOStatus.RELEASED
    wo.release_date = datetime.now()
    wo.engineering_released_at = datetime.now()
    wo.manufacturing_released_at = datetime.now()
    r1 = WORoute(
        work_order_id=wo.id,
        stage="F1",
        sequence=1,
        stage_target_qty=100,
        cumulative_ent_qty=100,
        cumulative_inproc_qty=100,
        stage_status="In-Progress",
    )
    w1 = StageWIP(
        work_order_id=wo.id,
        stage="F1",
        ent_qty=100,
        ok_qty=0,
        inproc_qty=100,
        onhand_qty=0,
        rejected_qty=0,
        received_qty=100,
        available_wip=100,
        moved_out_qty=0,
    )
    db_session.add_all([r1, w1])
    db_session.commit()

    res = client.post(
        "/api/v1/production/entry",
        headers=_auth_headers(admin),
        json={
            "wo_number": "WO-9001",
            "stage": "F1",
            "good_qty": 10,
            "rejected_quantity": 0,
        },
    )
    assert res.status_code == 400
    assert "uses Continuous Casting, which bypasses F1" in res.json()["detail"]


def test_8_continuous_wo_downstream_production_before_cc_cutting_rejected(client, db_session):
    """TEST 8: ACTIVE CC routing without reconciled cut blanks is rejected by usable blanks gate."""
    customer, part, order, wo, planner, _, admin = _seed_base_data(db_session)

    client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F1", "F2", "DISPATCH"],
            "casting_process": "CONTINUOUS",
        },
    )

    mat = ContinuousCastingMaterial(
        id=uuid.uuid4(),
        material_code="MAT-SG500-100",
        grade="SG 500/7",
        section="ROUND",
        stock_dimension_a_mm=100,
        is_active=True,
    )
    db_session.add(mat)
    db_session.flush()

    active_routing = ContinuousCastingRouting(
        id=uuid.uuid4(),
        work_order_id=wo.id,
        version=1,
        material_source=MATERIAL_SOURCE_CONTINUOUS_CASTING,
        status="ACTIVE",
        required_grade="SG 500/7",
        required_section="ROUND",
        finished_dimension_a_mm=90,
        finished_axial_length_mm=150,
        planned_blanks=100,
        blank_length_mm=160,
        machining_stock_a_mm=5,
        machining_stock_b_mm=5,
        kerf_mm=4,
        planned_cuts=100,
        end_trim_mm=20,
        gross_required_length_mm=16420,
        validated_material_id=mat.id,
        validated_by="planner",
        created_by="planner",
    )
    db_session.add(active_routing)
    db_session.commit()

    res = client.post(
        "/api/v1/production/entry",
        headers=_auth_headers(admin),
        json={
            "wo_number": "WO-9001",
            "stage": "F2",
            "good_qty": 5,
            "rejected_quantity": 0,
        },
    )
    assert res.status_code == 400
    assert "only 0 usable good blank(s) are available" in res.json()["detail"]


def test_9_continuous_wo_downstream_production_after_reconciled_cutting_allowed(client, db_session):
    """TEST 9: Production at F2 succeeds up to the quantity of reconciled good cut blanks."""
    customer, part, order, wo, planner, _, admin = _seed_base_data(db_session)

    client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F1", "F2", "DISPATCH"],
            "casting_process": "CONTINUOUS",
        },
    )

    mat = ContinuousCastingMaterial(
        id=uuid.uuid4(),
        material_code="MAT-SG500-100",
        grade="SG 500/7",
        section="ROUND",
        stock_dimension_a_mm=100,
        is_active=True,
    )
    inward = ContinuousCastingInward(
        id=uuid.uuid4(),
        inward_number="INW-000001",
        material_id=mat.id,
        grade="SG 500/7",
        section="ROUND",
        stock_dimension_a_mm=100,
        received_piece_count=1,
        received_total_length_mm=3000,
        qa_status="ACCEPTED",
    )
    db_session.add_all([mat, inward])
    db_session.flush()

    unit = ContinuousCastingStockUnit(
        id=uuid.uuid4(),
        inward_id=inward.id,
        unit_number="UNIT-0001",
        original_length_mm=3000,
        remaining_length_mm=1400,
        reserved_length_mm=0,
        issued_length_mm=0,
        consumed_length_mm=1600,
        status="IN_STOCK",
    )
    db_session.add(unit)
    db_session.flush()

    active_routing = ContinuousCastingRouting(
        id=uuid.uuid4(),
        work_order_id=wo.id,
        version=1,
        material_source=MATERIAL_SOURCE_CONTINUOUS_CASTING,
        status="ACTIVE",
        required_grade="SG 500/7",
        required_section="ROUND",
        finished_dimension_a_mm=90,
        finished_axial_length_mm=150,
        planned_blanks=100,
        blank_length_mm=160,
        machining_stock_a_mm=5,
        machining_stock_b_mm=5,
        kerf_mm=4,
        planned_cuts=100,
        end_trim_mm=20,
        gross_required_length_mm=16420,
        validated_material_id=mat.id,
        validated_by="planner",
        created_by="planner",
    )
    db_session.add(active_routing)
    db_session.flush()

    alloc = ContinuousCastingAllocation(
        id=uuid.uuid4(),
        routing_id=active_routing.id,
        stock_unit_id=unit.id,
        allocation_number="ALC-000001",
        planned_length_mm=1600,
        consumed_length_mm=1600,
        status="CONSUMED",
    )
    db_session.add(alloc)
    db_session.flush()

    ledger = ContinuousCastingStockLedger(
        id=uuid.uuid4(),
        transaction_number="TXN-000001",
        movement_type="CUT_CONSUME",
        inward_id=inward.id,
        stock_unit_id=unit.id,
        allocation_id=alloc.id,
        length_mm=1600,
        performed_by_name="operator",
    )
    db_session.add(ledger)
    db_session.flush()

    # Reconciled cut record with 10 good blanks
    cut = ContinuousCastingCutRecord(
        id=uuid.uuid4(),
        cut_number="CUT-000001",
        work_order_id=wo.id,
        allocation_id=alloc.id,
        stock_unit_id=unit.id,
        ledger_entry_id=ledger.id,
        planned_blanks=10,
        actual_good_blanks=10,
        rejected_blanks=0,
        blank_length_mm=160,
        actual_cuts=10,
        consumed_length_mm=1600,
        reconciliation_status="RECONCILED",
        variance_mm=0,
        performed_by_name="operator",
    )
    db_session.add(cut)
    db_session.commit()

    # Production entry of 6 pieces should succeed (10 usable available)
    res = client.post(
        "/api/v1/production/entry",
        headers=_auth_headers(admin),
        json={
            "wo_number": "WO-9001",
            "stage": "F2",
            "good_qty": 6,
            "rejected_quantity": 0,
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["good_qty"] == 6


def test_10_centrifugal_and_historical_wo_production_unaffected(client, db_session):
    """TEST 10: Centrifugal WO and Historical WO (casting_process=NULL) allow normal F1 production."""
    customer, part, order, wo, planner, _, admin = _seed_base_data(db_session)

    # 1. Centrifugal WO release
    client.post(
        "/api/v1/operations/wo-release",
        headers=_auth_headers(planner),
        json={
            "wo_number": "WO-9001",
            "physical_wo_qty": 100,
            "route_stages": ["F1", "F2", "DISPATCH"],
            "casting_process": "CENTRIFUGAL",
        },
    )

    res = client.post(
        "/api/v1/production/entry",
        headers=_auth_headers(admin),
        json={
            "wo_number": "WO-9001",
            "stage": "F1",
            "good_qty": 25,
            "rejected_quantity": 0,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["good_qty"] == 25

    # 2. Historical WO with casting_process = None
    wo.casting_process = None
    db_session.commit()

    res2 = client.post(
        "/api/v1/production/entry",
        headers=_auth_headers(admin),
        json={
            "wo_number": "WO-9001",
            "stage": "F1",
            "good_qty": 10,
            "rejected_quantity": 0,
        },
    )
    assert res2.status_code == 200, res2.text


def test_11_get_gate_status_reports_correct_verdicts(db_session):
    """TEST 11: get_gate_status returns accurate verdicts for CONTINUOUS, gated, and legacy WOs."""
    customer, part, order, wo, _, _, _ = _seed_base_data(db_session)

    # 1. Continuous without active routing -> BLOCKED_NO_ACTIVE_ROUTING
    wo.casting_process = "CONTINUOUS"
    db_session.commit()
    status1 = ContinuousCastingReadService.get_gate_status(db_session, "WO-9001")
    assert status1.verdict == "BLOCKED_NO_ACTIVE_ROUTING"
    assert status1.gate_applies is True

    # 2. Legacy WO without routing -> NOT_GATED
    wo.casting_process = None
    db_session.commit()
    status2 = ContinuousCastingReadService.get_gate_status(db_session, "WO-9001")
    assert status2.verdict == "NOT_GATED"
    assert status2.gate_applies is False
