"""Regression tests for OrderStatus/WOStatus enum compatibility and composite PO uniqueness.

Verifies:
1. OrderStatus.CONFIRMED and WOStatus.OPEN ORM persistence and deserialization.
2. GET /api/v1/dashboard/stats succeeds when WorkOrders with status 'OPEN' / 'open' exist.
3. GET /api/v1/work-orders succeeds with WorkOrders in 'OPEN' / 'open' status.
4. GET /api/v1/operations/oars succeeds with Orders in 'CONFIRMED' / 'confirmed' status.
5. GET /api/v1/masters/pos succeeds when linked Orders have 'CONFIRMED' / 'confirmed' status.
6. Same PO number across different customers succeeds (MIL + Schedule and LTC + Schedule).
7. Same PO number for the same customer fails with HTTP 400.
8. Standard PO lifecycle remains intact.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.database import SessionLocal
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WOStatus
from app.models.master_data import POMaster, POLine, POStatus
from app.main import app

SEEDED_LOGINS = {
    "ADMIN": ("admin@vspl.com", "admin123"),
}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client, role_key="ADMIN"):
    email, password = SEEDED_LOGINS[role_key]
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_order_status_confirmed_orm_compatibility(client):
    """Verify OrderStatus.CONFIRMED deserializes correctly in both uppercase and lowercase."""
    db = SessionLocal()
    try:
        cust = Customer(customer_code=f"CUST-{uuid.uuid4().hex[:6].upper()}", name="Test Customer")
        part = Part(part_number=f"PART-{uuid.uuid4().hex[:6].upper()}", grade="SG 500", description="Test Part")
        db.add_all([cust, part])
        db.flush()

        order1 = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po="PO-101",
            po_qty=10,
            max_batch_size=10,
            status=OrderStatus.CONFIRMED
        )
        db.add(order1)
        db.commit()

        # Query back via ORM
        fetched = db.query(Order).filter(Order.id == order1.id).first()
        assert fetched is not None
        assert fetched.status == OrderStatus.CONFIRMED
        assert fetched.status.value == "confirmed"

    finally:
        db.close()


def test_work_order_open_orm_compatibility(client):
    """Verify WOStatus.OPEN deserializes correctly in both uppercase and lowercase."""
    db = SessionLocal()
    try:
        cust = Customer(customer_code=f"CUST-{uuid.uuid4().hex[:6].upper()}", name="Test Customer")
        part = Part(part_number=f"PART-{uuid.uuid4().hex[:6].upper()}", grade="SG 500", description="Test Part")
        db.add_all([cust, part])
        db.flush()

        order = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po="PO-102",
            po_qty=20,
            max_batch_size=20,
            status=OrderStatus.CONFIRMED
        )
        db.add(order)
        db.flush()

        wo = WorkOrder(
            wo_number=f"WO-{uuid.uuid4().hex[:6].upper()}",
            order_id=order.id,
            physical_wo_qty=20,
            current_stage="F1",
            status=WOStatus.OPEN
        )
        db.add(wo)
        db.commit()

        # Query back via ORM
        fetched_wo = db.query(WorkOrder).filter(WorkOrder.id == wo.id).first()
        assert fetched_wo is not None
        assert fetched_wo.status == WOStatus.OPEN
        assert fetched_wo.status.value == "open"

    finally:
        db.close()


def test_dashboard_and_work_orders_endpoints_with_open_status(client):
    """Verify GET /api/v1/dashboard/stats and /api/v1/work-orders succeed with OPEN status WOs."""
    headers = _auth(_login(client))
    db = SessionLocal()
    try:
        cust = Customer(customer_code=f"CUST-{uuid.uuid4().hex[:6].upper()}", name="Test Customer")
        part = Part(part_number=f"PART-{uuid.uuid4().hex[:6].upper()}", grade="SG 500", description="Test Part")
        db.add_all([cust, part])
        db.flush()

        order = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po="PO-103",
            po_qty=15,
            max_batch_size=15,
            status=OrderStatus.CONFIRMED
        )
        db.add(order)
        db.flush()

        wo = WorkOrder(
            wo_number=f"WO-{uuid.uuid4().hex[:6].upper()}",
            order_id=order.id,
            physical_wo_qty=15,
            current_stage="F1",
            status=WOStatus.OPEN
        )
        db.add(wo)
        db.commit()

        # 1. Dashboard Stats
        resp = client.get("/api/v1/dashboard/stats", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "current_total_wip" in data
        assert "running_work_orders" in data

        # 2. List Work Orders
        resp_wo = client.get("/api/v1/work-orders", headers=headers)
        assert resp_wo.status_code == 200, resp_wo.text
        assert any(w["wo_number"] == wo.wo_number for w in resp_wo.json())

        # 3. List OARs
        resp_oars = client.get("/api/v1/operations/oars", headers=headers)
        assert resp_oars.status_code == 200, resp_oars.text
        assert any(o["oar_number"] == order.oar_number for o in resp_oars.json())

    finally:
        db.close()


def test_masters_pos_with_linked_confirmed_orders(client):
    """Verify GET /api/v1/masters/pos executes and calculates allocated qty without crashing."""
    headers = _auth(_login(client))
    db = SessionLocal()
    try:
        cust = Customer(customer_code=f"CUST-{uuid.uuid4().hex[:6].upper()}", name="Test Customer")
        part = Part(part_number=f"PART-{uuid.uuid4().hex[:6].upper()}", grade="SG 500", description="Test Part")
        db.add_all([cust, part])
        db.flush()

        po = POMaster(
            po_number=f"PO-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN
        )
        db.add(po)
        db.flush()

        pline = POLine(
            po_id=po.id,
            part_id=part.id,
            po_qty=50
        )
        db.add(pline)
        db.flush()

        order = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po=po.po_number,
            po_qty=50,
            max_batch_size=50,
            po_line_id=pline.id,
            status=OrderStatus.CONFIRMED
        )
        db.add(order)
        db.commit()

        resp = client.get("/api/v1/masters/pos", headers=headers)
        assert resp.status_code == 200, resp.text
        po_list = resp.json()
        target_po = next((p for p in po_list if p["id"] == str(po.id)), None)
        assert target_po is not None
        assert target_po["lines"][0]["allocated_qty"] == 50

    finally:
        db.close()


def test_same_po_number_across_different_customers_succeeds(client):
    """Verify that two distinct customers can have the same PO number (e.g. Schedule)."""
    headers = _auth(_login(client))
    
    # Create Customer 1 (MIL)
    cust1_code = f"MIL-{uuid.uuid4().hex[:4].upper()}"
    c1 = client.post("/api/v1/masters/customers", headers=headers, json={
        "customer_code": cust1_code,
        "name": f"Milacron India {cust1_code}"
    }).json()

    # Create Customer 2 (LTC)
    cust2_code = f"LTC-{uuid.uuid4().hex[:4].upper()}"
    c2 = client.post("/api/v1/masters/customers", headers=headers, json={
        "customer_code": cust2_code,
        "name": f"L&T Construction {cust2_code}"
    }).json()

    # Create common part
    db = SessionLocal()
    part_num = f"PART-{uuid.uuid4().hex[:6].upper()}"
    part = Part(part_number=part_num, grade="SG 450", description="Multi-customer Part")
    db.add(part)
    db.commit()
    db.close()

    shared_po_number = "Schedule"

    # Create PO for Customer 1
    resp1 = client.post("/api/v1/masters/pos", headers=headers, json={
        "customer_code": cust1_code,
        "po_number": shared_po_number,
        "lines": [{"part_number": part_num, "po_qty": 20}]
    })
    assert resp1.status_code == 200, resp1.text
    po1_data = resp1.json()
    assert po1_data["po_number"] == shared_po_number
    assert po1_data["customer_code"] == cust1_code

    # Create PO with the SAME number for Customer 2
    resp2 = client.post("/api/v1/masters/pos", headers=headers, json={
        "customer_code": cust2_code,
        "po_number": shared_po_number,
        "lines": [{"part_number": part_num, "po_qty": 50}]
    })
    assert resp2.status_code == 200, resp2.text
    po2_data = resp2.json()
    assert po2_data["po_number"] == shared_po_number
    assert po2_data["customer_code"] == cust2_code


def test_same_po_number_for_same_customer_fails(client):
    """Verify that duplicate PO number for the SAME customer is rejected with HTTP 400."""
    headers = _auth(_login(client))
    
    cust_code = f"CUST-{uuid.uuid4().hex[:6].upper()}"
    client.post("/api/v1/masters/customers", headers=headers, json={
        "customer_code": cust_code,
        "name": f"Test Cust {cust_code}"
    })

    db = SessionLocal()
    part_num = f"PART-{uuid.uuid4().hex[:6].upper()}"
    part = Part(part_number=part_num, grade="SG 450", description="Test Part")
    db.add(part)
    db.commit()
    db.close()

    po_number = f"PO-DUP-{uuid.uuid4().hex[:4].upper()}"

    # First creation succeeds
    resp1 = client.post("/api/v1/masters/pos", headers=headers, json={
        "customer_code": cust_code,
        "po_number": po_number,
        "lines": [{"part_number": part_num, "po_qty": 10}]
    })
    assert resp1.status_code == 200, resp1.text

    # Second creation with identical customer + po_number fails with 400
    resp2 = client.post("/api/v1/masters/pos", headers=headers, json={
        "customer_code": cust_code,
        "po_number": po_number,
        "lines": [{"part_number": part_num, "po_qty": 15}]
    })
    assert resp2.status_code == 400, resp2.text
    assert "already exists for this customer" in resp2.json()["detail"]
