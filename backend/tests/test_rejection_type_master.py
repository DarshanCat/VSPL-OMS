"""
Rejection Type Master regression suite: dedicated master (code/name/description/
active/created_by/updated_by/created_at/updated_at), Quality-only mutation RBAC,
backward-compatible activation of the Production Entry validation gate, and
historical-record preservation.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.core.security import hash_password, create_access_token
from app.models.user import User, UserRole
from app.models.order import Order, Part, Customer, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.models.production import ProductionUpdate
from app.models.nc import NCRecord
from app.models.rejection_type import RejectionType

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    yield db
    db.close()


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        yield test_db
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(db, email, role):
    user = User(full_name=email.split("@")[0], email=email, hashed_password=hash_password("x"), role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}, user


def _make_wo(db, wo_number, oar_number, qty, stages="F1 -> F2 -> DISPATCH"):
    customer = Customer(customer_code=f"C-{wo_number}", name="Test Customer")
    part = Part(part_number=f"P-{wo_number}", description="Test Part")
    db.add_all([customer, part])
    db.flush()
    order = Order(oar_number=oar_number, customer_id=customer.id, part_id=part.id, customer_po="PO-1",
                  po_qty=qty, max_batch_size=qty, status=OrderStatus.ACCEPT)
    db.add(order)
    db.flush()
    wo = WorkOrder(wo_number=wo_number, order_id=order.id, physical_wo_qty=qty,
                    current_stage="F1", projected_final_good=qty, status=WOStatus.IN_PRODUCTION)
    db.add(wo)
    db.flush()
    stage_list = [s.strip() for s in stages.split("->")]
    for seq, stg in enumerate(stage_list, start=1):
        db.add(WORoute(work_order_id=wo.id, stage=stg, sequence=seq, stage_target_qty=qty,
                        stage_status="In-Progress" if seq == 1 else "Pending"))
    db.add(StageWIP(work_order_id=wo.id, stage=stage_list[0], ent_qty=qty, ok_qty=0, inproc_qty=qty,
                     onhand_qty=0, rejected_qty=0, available_wip=qty))
    db.commit()
    db.refresh(wo)
    return wo


# ---------------------------------------------------------------------------
# Rejection Type CRUD + RBAC
# ---------------------------------------------------------------------------

def test_create_rejection_type_authorized(client, test_db):
    qa_headers, _ = _auth(test_db, "qa.rt1@vspl.com", UserRole.QA)
    resp = client.post("/api/v1/rejection/types", json={
        "code": "def-porosity", "name": "Porosity", "description": "Gas/shrinkage cavity"
    }, headers=qa_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == "DEF-POROSITY"
    assert body["is_active"] is True
    assert body["created_by"] == "qa.rt1"


def test_create_rejection_type_unauthorized(client, test_db):
    op_headers, _ = _auth(test_db, "op.rt2@vspl.com", UserRole.MACHINE_OPERATOR)
    resp = client.post("/api/v1/rejection/types", json={"code": "DEF-X", "name": "X"}, headers=op_headers)
    assert resp.status_code == 403


def test_duplicate_rejection_type_code_rejected(client, test_db):
    qa_headers, _ = _auth(test_db, "qa.rt3@vspl.com", UserRole.QA)
    client.post("/api/v1/rejection/types", json={"code": "DEF-DUP", "name": "A"}, headers=qa_headers)
    resp = client.post("/api/v1/rejection/types", json={"code": "DEF-DUP", "name": "B"}, headers=qa_headers)
    assert resp.status_code == 400


def test_edit_rejection_type_authorized(client, test_db):
    qa_headers, _ = _auth(test_db, "qa.rt4@vspl.com", UserRole.QA)
    created = client.post("/api/v1/rejection/types", json={"code": "DEF-EDIT", "name": "Old"}, headers=qa_headers).json()
    resp = client.put("/api/v1/rejection/types", json={"id": created["id"], "name": "New Name"}, headers=qa_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["updated_by"] == "qa.rt4"


def test_deactivate_rejection_type_authorized(client, test_db):
    qa_headers, _ = _auth(test_db, "qa.rt5@vspl.com", UserRole.QA)
    created = client.post("/api/v1/rejection/types", json={"code": "DEF-DEACT", "name": "N"}, headers=qa_headers).json()
    resp = client.put("/api/v1/rejection/types", json={"id": created["id"], "is_active": False}, headers=qa_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    op_headers, _ = _auth(test_db, "op.rt5@vspl.com", UserRole.MACHINE_OPERATOR)
    resp = client.put("/api/v1/rejection/types", json={"id": created["id"], "is_active": True}, headers=op_headers)
    assert resp.status_code == 403


def test_list_open_to_any_authenticated_user_active_only(client, test_db):
    qa_headers, _ = _auth(test_db, "qa.rt6@vspl.com", UserRole.QA)
    created = client.post("/api/v1/rejection/types", json={"code": "DEF-LIST", "name": "N"}, headers=qa_headers).json()
    client.put("/api/v1/rejection/types", json={"id": created["id"], "is_active": False}, headers=qa_headers)

    op_headers, _ = _auth(test_db, "op.rt6@vspl.com", UserRole.MACHINE_OPERATOR)
    resp = client.get("/api/v1/rejection/types", headers=op_headers)
    assert resp.status_code == 200
    assert not any(t["code"] == "DEF-LIST" for t in resp.json())

    # Even asking for inactive as a non-QA/ADMIN role is silently ignored.
    resp = client.get("/api/v1/rejection/types?include_inactive=true", headers=op_headers)
    assert not any(t["code"] == "DEF-LIST" for t in resp.json())

    resp = client.get("/api/v1/rejection/types?include_inactive=true", headers=qa_headers)
    assert any(t["code"] == "DEF-LIST" for t in resp.json())


# ---------------------------------------------------------------------------
# Production Entry integration: active-type validation gate
# ---------------------------------------------------------------------------

def test_inactive_type_cannot_be_selected_for_production_rejection(client, test_db):
    _make_wo(test_db, "WO-RT-1", "OAR-RT-1", 100)
    qa_headers, _ = _auth(test_db, "qa.rt7@vspl.com", UserRole.QA)
    op_headers, _ = _auth(test_db, "op.rt7@vspl.com", UserRole.MACHINE_OPERATOR)

    created = client.post("/api/v1/rejection/types", json={"code": "DEF-INACT", "name": "N"}, headers=qa_headers).json()
    client.put("/api/v1/rejection/types", json={"id": created["id"], "is_active": False}, headers=qa_headers)

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-RT-1", "stage": "F1", "good_qty": 5, "rejected_quantity": 2, "defect_code": "DEF-INACT"
    }, headers=op_headers)
    assert resp.status_code == 400
    assert "does not exist or is inactive" in resp.json()["detail"]


def test_active_type_can_be_selected_for_production_rejection(client, test_db):
    _make_wo(test_db, "WO-RT-2", "OAR-RT-2", 100)
    qa_headers, _ = _auth(test_db, "qa.rt8@vspl.com", UserRole.QA)
    op_headers, _ = _auth(test_db, "op.rt8@vspl.com", UserRole.MACHINE_OPERATOR)

    client.post("/api/v1/rejection/types", json={"code": "DEF-ACTIVE", "name": "N"}, headers=qa_headers)

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-RT-2", "stage": "F1", "good_qty": 5, "rejected_quantity": 2, "defect_code": "DEF-ACTIVE"
    }, headers=op_headers)
    assert resp.status_code == 200, resp.text


def test_rejection_type_required_when_rejected_qty_gt_zero_once_master_configured(client, test_db):
    _make_wo(test_db, "WO-RT-3", "OAR-RT-3", 100)
    qa_headers, _ = _auth(test_db, "qa.rt9@vspl.com", UserRole.QA)
    op_headers, _ = _auth(test_db, "op.rt9@vspl.com", UserRole.MACHINE_OPERATOR)

    client.post("/api/v1/rejection/types", json={"code": "DEF-ANY", "name": "N"}, headers=qa_headers)

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-RT-3", "stage": "F1", "good_qty": 5, "rejected_quantity": 2
    }, headers=op_headers)
    assert resp.status_code == 400
    assert "Rejection Type is required" in resp.json()["detail"]


def test_rejection_type_not_required_when_rejected_qty_is_zero(client, test_db):
    _make_wo(test_db, "WO-RT-4", "OAR-RT-4", 100)
    qa_headers, _ = _auth(test_db, "qa.rt10@vspl.com", UserRole.QA)
    op_headers, _ = _auth(test_db, "op.rt10@vspl.com", UserRole.MACHINE_OPERATOR)

    client.post("/api/v1/rejection/types", json={"code": "DEF-ANY2", "name": "N"}, headers=qa_headers)

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-RT-4", "stage": "F1", "good_qty": 5, "rejected_quantity": 0
    }, headers=op_headers)
    assert resp.status_code == 200, resp.text


def test_arbitrary_free_text_defect_code_rejected_even_when_master_empty(client, test_db):
    """Mandatory-by-default: validation must reject an arbitrary/unconfigured
    defect_code even when this test's isolated DB has zero RejectionType rows --
    a real deployment never actually hits an empty master because
    seed_database_if_empty seeds default types on every startup (see
    test_default_seeded_rejection_type_accepted_without_manual_configuration
    below), but the gate itself must never fall back to accepting free text."""
    _make_wo(test_db, "WO-RT-5", "OAR-RT-5", 100)
    op_headers, _ = _auth(test_db, "op.rt11@vspl.com", UserRole.MACHINE_OPERATOR)

    assert test_db.query(RejectionType).count() == 0
    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-RT-5", "stage": "F1", "good_qty": 5, "rejected_quantity": 2, "defect_code": "ANY-ARBITRARY-STRING"
    }, headers=op_headers)
    assert resp.status_code == 400
    assert "does not exist or is inactive" in resp.json()["detail"]


def test_default_seeded_rejection_type_accepted_without_manual_configuration(client, test_db):
    """Requirement: a fresh deployment must not require Quality to manually create
    the first RejectionType before Production Entry's validation works --
    seed_database_if_empty (via _seed_default_rejection_types) seeds a safe default
    set on every app startup, in every environment, so validation works out of the
    box."""
    from app.services.seed_service import _seed_default_rejection_types
    _seed_default_rejection_types(test_db)
    test_db.commit()

    _make_wo(test_db, "WO-RT-SEED", "OAR-RT-SEED", 100)
    op_headers, _ = _auth(test_db, "op.rtseed@vspl.com", UserRole.MACHINE_OPERATOR)

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-RT-SEED", "stage": "F1", "good_qty": 5, "rejected_quantity": 2, "defect_code": "DEF-POROSITY"
    }, headers=op_headers)
    assert resp.status_code == 200, resp.text


def test_historical_rejection_records_remain_intact_after_type_deactivation(client, test_db):
    """Deactivating a Rejection Type must never rewrite already-recorded
    NCRecord.defect_code values."""
    wo = _make_wo(test_db, "WO-RT-6", "OAR-RT-6", 100)
    qa_headers, _ = _auth(test_db, "qa.rt12@vspl.com", UserRole.QA)
    op_headers, _ = _auth(test_db, "op.rt12@vspl.com", UserRole.MACHINE_OPERATOR)

    created = client.post("/api/v1/rejection/types", json={"code": "DEF-HIST", "name": "N"}, headers=qa_headers).json()

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-RT-6", "stage": "F1", "good_qty": 5, "rejected_quantity": 2, "defect_code": "DEF-HIST"
    }, headers=op_headers)
    assert resp.status_code == 200

    nc = test_db.query(NCRecord).filter(NCRecord.work_order_id == wo.id).first()
    assert nc is not None
    assert nc.defect_code == "DEF-HIST"

    client.put("/api/v1/rejection/types", json={"id": created["id"], "is_active": False}, headers=qa_headers)

    test_db.refresh(nc)
    assert nc.defect_code == "DEF-HIST"  # never rewritten
