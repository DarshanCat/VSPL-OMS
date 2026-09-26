"""
Packing Unit Code, Dispatch invoice requirement, Stage-wise report Delivery Date,
and Roles & Responsibilities regression suite.
"""
import pytest
from datetime import date
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
from app.models.packing import PackingTransaction
from app.services.report_service import ReportService

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


def _make_wo(db, wo_number, oar_number, qty, stages="F1 -> PACKING -> DISPATCH", delivery_date=None):
    customer = Customer(customer_code=f"C-{wo_number}", name="Test Customer")
    part = Part(part_number=f"P-{wo_number}", description="Test Part")
    db.add_all([customer, part])
    db.flush()
    order = Order(oar_number=oar_number, customer_id=customer.id, part_id=part.id, customer_po="PO-1",
                  po_qty=qty, max_batch_size=qty, status=OrderStatus.ACCEPT, delivery_date=delivery_date)
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
# Packing Unit Code
# ---------------------------------------------------------------------------

def test_packing_unit_code_generated_and_unique(client, test_db):
    wo1 = _make_wo(test_db, "WO-PKU-1", "OAR-PKU-1", 50)
    wo2 = _make_wo(test_db, "WO-PKU-2", "OAR-PKU-2", 50)
    packing_headers, _ = _auth(test_db, "pack.pku@vspl.com", UserRole.PACKING)

    resp1 = client.post("/api/v1/packing/update", json={
        "wo_number": "WO-PKU-1", "packed_quantity": 50
    }, headers=packing_headers)
    assert resp1.status_code == 200, resp1.text
    code1 = resp1.json()["packing_unit_code"]
    assert code1 is not None and code1.startswith("PKU-")

    resp2 = client.post("/api/v1/packing/update", json={
        "wo_number": "WO-PKU-2", "packed_quantity": 50
    }, headers=packing_headers)
    assert resp2.status_code == 200
    code2 = resp2.json()["packing_unit_code"]
    assert code2 is not None
    assert code2 != code1

    txns = test_db.query(PackingTransaction).all()
    assert len(txns) == 2
    assert {t.packing_unit_code for t in txns} == {code1, code2}


def test_packing_unit_code_unique_per_transaction_not_reused(client, test_db):
    wo = _make_wo(test_db, "WO-PKU-3", "OAR-PKU-3", 50)
    packing_headers, _ = _auth(test_db, "pack.pku3@vspl.com", UserRole.PACKING)

    r1 = client.post("/api/v1/packing/update", json={"wo_number": "WO-PKU-3", "packed_quantity": 30}, headers=packing_headers)
    code1 = r1.json()["packing_unit_code"]
    r2 = client.post("/api/v1/packing/update", json={"wo_number": "WO-PKU-3", "packed_quantity": 20}, headers=packing_headers)
    code2 = r2.json()["packing_unit_code"]
    assert code1 != code2


# ---------------------------------------------------------------------------
# Dispatch requires invoice number
# ---------------------------------------------------------------------------

def test_dispatch_requires_invoice_number_schema_level(client, test_db):
    _make_wo(test_db, "WO-DSP-1", "OAR-DSP-1", 10)
    dispatch_headers, _ = _auth(test_db, "dispatch.dsp1@vspl.com", UserRole.DISPATCH)

    resp = client.post("/api/v1/dispatch/ship", json={
        "wo_number": "WO-DSP-1", "dispatched_quantity": 5
    }, headers=dispatch_headers)
    assert resp.status_code == 422  # pydantic: invoice_number is required


def test_dispatch_requires_invoice_number_backend_level_blank_string(test_db):
    """Blank/whitespace-only invoice numbers are rejected server-side too, not only
    relying on the frontend/schema."""
    from app.services.dispatch_service import DispatchService
    from app.schemas.dispatch import DispatchRequest
    from fastapi import HTTPException

    _make_wo(test_db, "WO-DSP-2", "OAR-DSP-2", 10)
    req = DispatchRequest(wo_number="WO-DSP-2", invoice_number="   ", dispatched_quantity=5)
    with pytest.raises(HTTPException) as exc:
        DispatchService.execute_dispatch(test_db, req, current_user=None)
    assert exc.value.status_code == 400
    assert "Invoice Number" in exc.value.detail


# ---------------------------------------------------------------------------
# Stage-wise report: Delivery Date
# ---------------------------------------------------------------------------

def test_wip_csv_includes_delivery_date(test_db):
    _make_wo(test_db, "WO-RPT-1", "OAR-RPT-1", 50, delivery_date=date(2026, 3, 15))
    csv_content = ReportService.generate_wip_csv(test_db)
    header = csv_content.splitlines()[0].split(",")
    assert "Delivery Date" in header
    data_line = csv_content.splitlines()[1]
    assert "2026-03-15" in data_line


# ---------------------------------------------------------------------------
# Roles & Responsibilities page
# ---------------------------------------------------------------------------

def test_roles_page_lists_every_role(client, test_db):
    headers, _ = _auth(test_db, "any.role.viewer@vspl.com", UserRole.DATA_ANALYST)
    resp = client.get("/api/v1/roles", headers=headers)
    assert resp.status_code == 200
    roles = {r["display_name"] for r in resp.json()}
    expected = {
        "SUPER_ADMIN", "PLANNER", "ENGINEERING", "MANUFACTURING", "PRODUCTION_MANAGER",
        "STORE", "QUALITY", "DISPATCH", "CEO", "DATA_ANALYST"
    }
    assert expected.issubset(roles)


def test_roles_page_requires_authentication(client, test_db):
    resp = client.get("/api/v1/roles")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Existing RBAC regression -- spot check a few unrelated endpoints still enforce
# the SAME role tuples as before these changes.
# ---------------------------------------------------------------------------

def test_existing_rbac_regression_production_entry_still_gated(client, test_db):
    _make_wo(test_db, "WO-RBAC-1", "OAR-RBAC-1", 10)
    sales_headers, _ = _auth(test_db, "sales.rbac1@vspl.com", UserRole.SALES)
    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-RBAC-1", "stage": "F1", "good_qty": 5, "rejected_quantity": 0
    }, headers=sales_headers)
    assert resp.status_code == 403


def test_existing_rbac_regression_dispatch_still_gated(client, test_db):
    _make_wo(test_db, "WO-RBAC-2", "OAR-RBAC-2", 10)
    sales_headers, _ = _auth(test_db, "sales.rbac2@vspl.com", UserRole.SALES)
    resp = client.post("/api/v1/dispatch/ship", json={
        "wo_number": "WO-RBAC-2", "invoice_number": "INV-1", "dispatched_quantity": 5
    }, headers=sales_headers)
    assert resp.status_code == 403
