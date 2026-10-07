import uuid
from datetime import datetime, date, timezone
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import Base, engine, SessionLocal
from app.models.user import User, UserRole
from app.models.order import Customer, Part, Order, OrderStatus, OrderClassification
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.machine import Machine
from app.models.operator import Operator
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.audit import AuditLog
from app.models.manufacturing import WOManufacturingReadiness, ChecklistItemStatus
from app.models.continuous_casting import (
    ContinuousCastingMaterial, ContinuousCastingInward, ContinuousCastingStockUnit,
    ContinuousCastingRouting, ContinuousCastingAllocation, ContinuousCastingStockLedger,
    ContinuousCastingCutRecord,
)
from app.core.security import create_access_token
from app.core.rate_limit import limiter
from app.schemas.operations import WOReleaseCreate
from app.services.operations_service import OperationsService


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _create_user(db: Session, email: str, role: UserRole, full_name: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            id=uuid.uuid4(),
            email=email,
            full_name=full_name,
            hashed_password="hashed_test_password",
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _auth_headers(user: User) -> dict:
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


def _setup_base_data(db: Session):
    customer = db.query(Customer).first()
    if not customer:
        customer = Customer(
            id=uuid.uuid4(),
            customer_code="CUST-MFG-001",
            name="Manufacturing Test Customer",
            is_active=True,
        )
        db.add(customer)
        db.flush()

    part = db.query(Part).first()
    if not part:
        part = Part(
            id=uuid.uuid4(),
            part_number="PART-MFG-001",
            description="Machined Cylinder Sleeve",
            grade="EN-GJL-250",
        )
        db.add(part)
        db.flush()

    machine = db.query(Machine).filter(Machine.machine_code == "CNC-TEST-01").first()
    if not machine:
        machine = Machine(
            id=uuid.uuid4(),
            machine_code="CNC-TEST-01",
            machine_name="Mazak QuickTurn CNC 01",
            department="Machine Shop",
            is_active=True,
        )
        db.add(machine)
        db.flush()

    operator = db.query(Operator).filter(Operator.employee_code == "OP-TEST-01").first()
    if not operator:
        operator = Operator(
            id=uuid.uuid4(),
            employee_code="OP-TEST-01",
            display_name="Rajesh Kumar",
            is_active=True,
        )
        db.add(operator)
        db.flush()

    db.commit()
    return customer, part, machine, operator


def _unique(prefix="MFG"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _create_work_order(db: Session, wo_num: str, part: Part, customer: Customer, is_replacement=False, is_npd=False) -> WorkOrder:
    order = Order(
        id=uuid.uuid4(),
        oar_number=f"OAR-{wo_num}-{uuid.uuid4().hex[:6].upper()}",
        customer_id=customer.id,
        part_id=part.id,
        customer_po=f"PO-{wo_num}",
        po_qty=100,
        max_batch_size=100,
        status=OrderStatus.ACCEPT,
        order_classification="npd" if is_npd else "regular",
        delivery_date=date.today(),
    )
    db.add(order)
    db.flush()

    wo = WorkOrder(
        id=uuid.uuid4(),
        wo_number=wo_num,
        order_id=order.id,
        physical_wo_qty=100,
        status=WOStatus.PLANNED,
        is_replacement=is_replacement,
        replacement_reason="Previous casting scrapped at proof turn" if is_replacement else None,
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return wo


# ==============================================================================
# 1. CHECKLIST ITEM STATUS & VALIDATION TESTS (READY, NOT_READY, N_A, EXCEPTION)
# ==============================================================================

def test_checklist_update_and_na_rules(client, db_session):
    customer, part, machine, operator = _setup_base_data(db_session)
    wo = _create_work_order(db_session, _unique("WO-MFG1"), part, customer)
    mfg_user = _create_user(db_session, "mfg1@vspl.com", UserRole.MANUFACTURING, "Mfg Specialist")
    headers = _auth_headers(mfg_user)

    # 1. N/A is forbidden on Material Staging -> should fail with 400
    res = client.put(
        f"/api/v1/manufacturing/readiness/{wo.wo_number}",
        json={"material_staging_status": "N_A"},
        headers=headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "N/A is not permitted for Material Staging" in res.json()["detail"]

    # 2. N/A is forbidden on Machine Capacity -> should fail with 400
    res = client.put(
        f"/api/v1/manufacturing/readiness/{wo.wo_number}",
        json={"machine_capacity_status": "N_A"},
        headers=headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "N/A is not permitted for Machine Cell & Capacity" in res.json()["detail"]

    # 3. N/A is forbidden on Operator Manning -> should fail with 400
    res = client.put(
        f"/api/v1/manufacturing/readiness/{wo.wo_number}",
        json={"operator_manning_status": "N_A"},
        headers=headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "N/A is not permitted for Operator Manning" in res.json()["detail"]

    # 4. Valid update with READY, N_A (with remark), and EXCEPTION (with remark)
    res = client.put(
        f"/api/v1/manufacturing/readiness/{wo.wo_number}",
        json={
            "material_staging_status": "READY",
            "machine_capacity_status": "EXCEPTION",
            "machine_capacity_remark": "Alternate machine CNC-04 assigned",
            "machine_id": str(machine.id),
            "tooling_fixtures_status": "N_A",
            "tooling_fixtures_remark": "Standard 3-jaw chuck used; no special fixture required",
            "cnc_program_setup_status": "READY",
            "nc_program_number": "NC-CYL-01",
            "gauges_quality_status": "READY",
            "gauge_set_id": "GAUGE-SET-44",
            "operator_manning_status": "READY",
            "operator_id": str(operator.id),
            "document_name": "Setup-Sheet-01.pdf",
            "document_revision": "Rev 02",
        },
        headers=headers,
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["material_staging_status"] == "READY"
    assert data["machine_capacity_status"] == "EXCEPTION"
    assert data["machine_capacity_remark"] == "Alternate machine CNC-04 assigned"
    assert data["machine_code"] == machine.machine_code
    assert data["tooling_fixtures_status"] == "N_A"
    assert data["tooling_fixtures_remark"] == "Standard 3-jaw chuck used; no special fixture required"
    assert data["operator_name"] == operator.display_name


# ==============================================================================
# 2. ENGINEERING RELEASE PREREQUISITE & BLOCKING RULES
# ==============================================================================

def test_manufacturing_release_requires_engineering_release(client, db_session):
    customer, part, machine, operator = _setup_base_data(db_session)
    wo = _create_work_order(db_session, _unique("WO-MFG2"), part, customer)
    mfg_user = _create_user(db_session, "mfg2@vspl.com", UserRole.MANUFACTURING, "Mfg Lead")
    headers = _auth_headers(mfg_user)

    # Set all 6 checks to READY
    client.put(
        f"/api/v1/manufacturing/readiness/{wo.wo_number}",
        json={
            "material_staging_status": "READY",
            "machine_capacity_status": "READY",
            "tooling_fixtures_status": "READY",
            "cnc_program_setup_status": "READY",
            "gauges_quality_status": "READY",
            "operator_manning_status": "READY",
        },
        headers=headers,
    )

    # Attempt Manufacturing Release while engineering_released_at is None
    res = client.post(
        f"/api/v1/manufacturing/release/{wo.wo_number}",
        json={"document_name": "Process-Plan-002.pdf"},
        headers=headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Engineering Release is pending" in res.json()["detail"]


def test_missing_remark_on_na_or_exception_blocks_release(client, db_session):
    customer, part, machine, operator = _setup_base_data(db_session)
    wo = _create_work_order(db_session, _unique("WO-MFG3"), part, customer)
    wo.engineering_released_by = "Engineer Dave"
    wo.engineering_released_at = datetime.now(timezone.utc)
    db_session.commit()

    mfg_user = _create_user(db_session, "mfg3@vspl.com", UserRole.MANUFACTURING, "Mfg Specialist")
    headers = _auth_headers(mfg_user)

    # Tooling marked N_A but NO remark provided
    client.put(
        f"/api/v1/manufacturing/readiness/{wo.wo_number}",
        json={
            "material_staging_status": "READY",
            "machine_capacity_status": "READY",
            "tooling_fixtures_status": "N_A",
            "tooling_fixtures_remark": "",  # Empty remark!
            "cnc_program_setup_status": "READY",
            "gauges_quality_status": "READY",
            "operator_manning_status": "READY",
        },
        headers=headers,
    )

    # Attempt release -> must fail
    res = client.post(
        f"/api/v1/manufacturing/release/{wo.wo_number}",
        json={"document_name": "Process-Plan.pdf"},
        headers=headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "N/A requires a mandatory justification remark" in res.json()["detail"]


# ==============================================================================
# 3. SUCCESSFUL MANUFACTURING RELEASE & AUTHORITATIVE WO WRITES
# ==============================================================================

def test_successful_manufacturing_release_populates_authoritative_fields(client, db_session):
    customer, part, machine, operator = _setup_base_data(db_session)
    wo = _create_work_order(db_session, _unique("WO-MFG4"), part, customer)
    wo.engineering_released_by = "Engineer Alice"
    wo.engineering_released_at = datetime.now(timezone.utc)
    db_session.commit()

    mfg_user = _create_user(db_session, "mfg4@vspl.com", UserRole.MANUFACTURING, "Anand Kumar")
    headers = _auth_headers(mfg_user)

    # Populate all 6 checks
    client.put(
        f"/api/v1/manufacturing/readiness/{wo.wo_number}",
        json={
            "material_staging_status": "READY",
            "machine_capacity_status": "READY",
            "machine_id": str(machine.id),
            "tooling_fixtures_status": "READY",
            "fixture_id": "JIG-44",
            "cnc_program_setup_status": "READY",
            "nc_program_number": "NC-CYL-04",
            "gauges_quality_status": "READY",
            "gauge_set_id": "PLUG-GAUGE-50",
            "operator_manning_status": "READY",
            "operator_id": str(operator.id),
        },
        headers=headers,
    )

    # Authorize release
    res = client.post(
        f"/api/v1/manufacturing/release/{wo.wo_number}",
        json={
            "document_name": "MFG-ROUTING-PLAN.pdf",
            "document_url": "https://storage.googleapis.com/vspl-docs/mfg-plan.pdf",
            "document_revision": "Rev 03",
            "remarks": "Tooling and CNC program verified on shop floor.",
        },
        headers=headers,
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["is_released"] is True
    assert data["manufacturing_released_by"] == "Anand Kumar"
    assert data["manufacturing_released_at"] is not None

    # Verify authoritative WorkOrder columns in DB
    db_session.refresh(wo)
    assert wo.manufacturing_released_by == "Anand Kumar"
    assert wo.manufacturing_released_at is not None
    assert wo.manufacturing_document_name == "MFG-ROUTING-PLAN.pdf"
    assert wo.manufacturing_document_url == "https://storage.googleapis.com/vspl-docs/mfg-plan.pdf"
    assert wo.manufacturing_document_revision == "Rev 03"
    assert wo.manufacturing_remarks == "Tooling and CNC program verified on shop floor."
    # WO status must NOT be changed to RELEASED by Manufacturing Release
    assert wo.status == WOStatus.PLANNED

    # Verify AuditLog entry
    audit = db_session.query(AuditLog).filter(
        AuditLog.entity_id == wo.wo_number,
        AuditLog.action == "MANUFACTURING_RELEASE",
    ).first()
    assert audit is not None
    assert "Anand Kumar" in audit.new_value


# ==============================================================================
# 4. RBAC MATRIX TESTS
# ==============================================================================

@pytest.mark.parametrize("role,should_succeed", [
    (UserRole.ADMIN, True),
    (UserRole.MANUFACTURING, True),
    (UserRole.PRODUCTION_MANAGER, True),
    (UserRole.PLANNER, False),
    (UserRole.ENGINEERING, False),
    (UserRole.OPERATOR, False),
    (UserRole.QA, False),
    (UserRole.STORE, False),
    (UserRole.DISPATCH, False),
])
def test_rbac_manufacturing_release_permissions(client, db_session, role, should_succeed):
    customer, part, machine, operator = _setup_base_data(db_session)
    wo = _create_work_order(db_session, _unique(f"WO-RBAC-{role.value}"), part, customer)
    wo.engineering_released_by = "Engineer Alice"
    wo.engineering_released_at = datetime.now(timezone.utc)
    db_session.commit()

    # Pre-populate ready checklist
    readiness = WOManufacturingReadiness(
        id=uuid.uuid4(),
        work_order_id=wo.id,
        material_staging_status="READY",
        machine_capacity_status="READY",
        tooling_fixtures_status="READY",
        cnc_program_setup_status="READY",
        gauges_quality_status="READY",
        operator_manning_status="READY",
        readiness_status="READY",
    )
    db_session.add(readiness)
    db_session.commit()

    user = _create_user(db_session, f"user_{role.value}@vspl.com", role, f"User {role.value}")
    headers = _auth_headers(user)

    res = client.post(
        f"/api/v1/manufacturing/release/{wo.wo_number}",
        json={"document_name": "Process-Plan.pdf"},
        headers=headers,
    )

    if should_succeed:
        assert res.status_code == status.HTTP_200_OK
    else:
        assert res.status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# 5. REVOCATION LIFECYCLE & PRODUCTION SAFETY GATES
# ==============================================================================

def test_manufacturing_revocation_and_production_block(client, db_session):
    customer, part, machine, operator = _setup_base_data(db_session)
    wo = _create_work_order(db_session, _unique("WO-MFG-REV"), part, customer)
    wo.engineering_released_by = "Engineer Alice"
    wo.engineering_released_at = datetime.now(timezone.utc)
    wo.manufacturing_released_by = "Mfg Lead"
    wo.manufacturing_released_at = datetime.now(timezone.utc)
    wo.manufacturing_document_name = "MFG-PLAN.pdf"
    db_session.commit()

    admin_user = _create_user(db_session, "admin_mfg@vspl.com", UserRole.ADMIN, "Super Admin")
    mfg_user = _create_user(db_session, "mfg_lead@vspl.com", UserRole.MANUFACTURING, "Mfg Lead")
    admin_headers = _auth_headers(admin_user)
    mfg_headers = _auth_headers(mfg_user)

    # 1. Non-admin cannot revoke -> 403
    res = client.post(
        f"/api/v1/manufacturing/revoke/{wo.wo_number}",
        json={"revocation_reason": "Drawing mismatch"},
        headers=mfg_headers,
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN

    # 2. Admin cannot revoke without reason -> 400
    res = client.post(
        f"/api/v1/manufacturing/revoke/{wo.wo_number}",
        json={"revocation_reason": "   "},
        headers=admin_headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST

    # 3. Admin revocation succeeds when no production movement has occurred
    res = client.post(
        f"/api/v1/manufacturing/revoke/{wo.wo_number}",
        json={"revocation_reason": "Tooling fixture needs calibration re-check"},
        headers=admin_headers,
    )
    assert res.status_code == status.HTTP_200_OK
    db_session.refresh(wo)
    assert wo.manufacturing_released_at is None
    assert wo.manufacturing_released_by is None

    # 4. Now re-release and simulate shop-floor production movement
    wo.manufacturing_released_by = "Mfg Lead"
    wo.manufacturing_released_at = datetime.now(timezone.utc)
    db_session.commit()

    movement = ProductionMovement(
        id=uuid.uuid4(),
        movement_id=_unique("MOV-MFG"),
        work_order_id=wo.id,
        from_stage="F1",
        to_stage="F2",
        quantity_moved=10,
    )
    db_session.add(movement)
    db_session.commit()

    # Attempt revocation after movement commenced -> must be blocked
    res = client.post(
        f"/api/v1/manufacturing/revoke/{wo.wo_number}",
        json={"revocation_reason": "Attempting late revoke"},
        headers=admin_headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Shop floor production/movement has already commenced" in res.json()["detail"]


# ==============================================================================
# 6. PLANNER WO RELEASE GATE ENFORCEMENT & ZERO-MUTATION VERIFICATION
# ==============================================================================

def test_planner_wo_release_gate_enforcement(client, db_session):
    customer, part, machine, operator = _setup_base_data(db_session)
    planner_user = _create_user(db_session, "planner_gate@vspl.com", UserRole.PLANNER, "PPC Planner")

    # --- Scenario A: WO with neither gate passed ---
    wo_a = _create_work_order(db_session, _unique("WO-GATE-A"), part, customer)
    
    # Call Planner release via service
    with pytest.raises(Exception) as exc_info:
        OperationsService.release_work_order(
            db_session,
            WOReleaseCreate(wo_number=wo_a.wo_number, physical_wo_qty=100, route_stages=["F1", "F2", "FI", "DISPATCH"]),
            current_user=planner_user,
        )
    assert "Engineering Release is pending" in str(exc_info.value)
    
    # Verify ZERO route / WIP mutation occurred
    db_session.refresh(wo_a)
    assert wo_a.status == WOStatus.PLANNED
    assert wo_a.release_date is None
    assert len(wo_a.routes) == 0
    assert len(wo_a.stage_wips) == 0

    # --- Scenario B: WO with Engineering passed but Manufacturing pending ---
    wo_b = _create_work_order(db_session, _unique("WO-GATE-B"), part, customer)
    wo_b.engineering_released_by = "Engineer Dave"
    wo_b.engineering_released_at = datetime.now(timezone.utc)
    db_session.commit()

    with pytest.raises(Exception) as exc_info:
        OperationsService.release_work_order(
            db_session,
            WOReleaseCreate(wo_number=wo_b.wo_number, physical_wo_qty=100, route_stages=["F1", "F2", "FI", "DISPATCH"]),
            current_user=planner_user,
        )
    assert "Manufacturing Release is pending" in str(exc_info.value)

    # Verify ZERO route / WIP mutation occurred
    db_session.refresh(wo_b)
    assert wo_b.status == WOStatus.PLANNED
    assert wo_b.release_date is None
    assert len(wo_b.routes) == 0

    # --- Scenario C: WO with BOTH Engineering & Manufacturing passed ---
    wo_c = _create_work_order(db_session, _unique("WO-GATE-C"), part, customer)
    wo_c.engineering_released_by = "Engineer Dave"
    wo_c.engineering_released_at = datetime.now(timezone.utc)
    wo_c.manufacturing_released_by = "Mfg Anand"
    wo_c.manufacturing_released_at = datetime.now(timezone.utc)
    db_session.commit()

    # Planner release must now succeed
    res = OperationsService.release_work_order(
        db_session,
        WOReleaseCreate(wo_number=wo_c.wo_number, physical_wo_qty=100, route_stages=["F1", "F2", "FI", "DISPATCH"]),
        current_user=planner_user,
    )
    assert res.success is True
    db_session.refresh(wo_c)
    assert wo_c.status == WOStatus.RELEASED
    assert wo_c.release_date is not None
    assert len(wo_c.routes) == 4
    assert len(wo_c.stage_wips) == 1


def test_legacy_and_replacement_wo_compatibility(client, db_session):
    customer, part, machine, operator = _setup_base_data(db_session)
    planner_user = _create_user(db_session, "planner_leg@vspl.com", UserRole.PLANNER, "PPC Planner")

    # 1. Historical already-released legacy WO with release_date
    wo_legacy = _create_work_order(db_session, _unique("WO-LEGACY"), part, customer)
    wo_legacy.status = WOStatus.IN_PRODUCTION
    wo_legacy.release_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    wo_legacy.released_by = "Old Planner"
    db_session.commit()

    # Legacy WO re-release does not crash
    res = OperationsService.release_work_order(
        db_session,
        WOReleaseCreate(wo_number=wo_legacy.wo_number, physical_wo_qty=100, route_stages=["F1", "F2", "FI", "DISPATCH"]),
        current_user=planner_user,
    )
    assert res.success is True

    # 2. Replacement WO MUST strictly require both gates even if status was manipulated
    wo_rep = _create_work_order(db_session, _unique("WO-REP"), part, customer, is_replacement=True)
    with pytest.raises(Exception) as exc_info:
        OperationsService.release_work_order(
            db_session,
            WOReleaseCreate(wo_number=wo_rep.wo_number, physical_wo_qty=50, route_stages=["F1", "F2", "DISPATCH"]),
            current_user=planner_user,
        )
    assert "Engineering Release is pending" in str(exc_info.value)
