import uuid
import pytest
from starlette.testclient import TestClient
from app.main import app
from app.models.order import Order
from app.core.database import SessionLocal, auto_migrate_schema

@pytest.fixture(autouse=True)
def _setup():
    auto_migrate_schema()

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def _login(client, role="ADMIN"):
    resp = client.post("/api/v1/auth/login", json={"email": "admin@vspl.com", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]

def _auth(token):
    return {"Authorization": f"Bearer {token}"}

def test_multi_part_same_po_shares_one_oar(client):
    """Real customer POs have multiple parts. All parts for the same Customer PO share ONE OAR."""
    headers = _auth(_login(client))
    po_num = f"PO-MULTI-{uuid.uuid4().hex[:6].upper()}"
    oar_num = f"OAR-M-{uuid.uuid4().hex[:6].upper()}"

    # Line 1: Part 1
    resp1 = client.post(
        "/api/v1/operations/intake",
        headers=headers,
        json={
            "customer_code": "CUST-VALVE",
            "customer_name": "Flowserve Controls Ltd",
            "customer_po": po_num,
            "part_number": "BRZ-BUSH-100",
            "po_quantity": 50,
            "commitment_date": "2026-10-30",
            "oar_number": oar_num,
            "create_wos": False,
        },
    )
    assert resp1.status_code == 200, resp1.text
    body1 = resp1.json()
    assert body1["oar_number"] == oar_num

    # Line 2: Part 2 under the SAME PO using the SAME OAR number
    resp2 = client.post(
        "/api/v1/operations/intake",
        headers=headers,
        json={
            "customer_code": "CUST-VALVE",
            "customer_name": "Flowserve Controls Ltd",
            "customer_po": po_num,
            "part_number": "BRZ-RING-250",
            "po_quantity": 75,
            "commitment_date": "2026-11-15",
            "oar_number": oar_num,
            "create_wos": False,
        },
    )
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert body2["oar_number"] == oar_num

    # Verify both orders in DB have the same OAR and their commitment dates
    db = SessionLocal()
    try:
        orders = db.query(Order).filter(Order.oar_number == oar_num).all()
        assert len(orders) == 2
        pns = {o.part.part_number for o in orders}
        assert "BRZ-BUSH-100" in pns
        assert "BRZ-RING-250" in pns
        for o in orders:
            assert o.commitment_date is not None
    finally:
        db.close()

    # Line 3: Another PO trying to reuse this OAR number MUST fail with 400
    resp3 = client.post(
        "/api/v1/operations/intake",
        headers=headers,
        json={
            "customer_code": "CUST-VALVE",
            "customer_name": "Flowserve Controls Ltd",
            "customer_po": f"PO-DIFFERENT-{uuid.uuid4().hex[:6]}",
            "part_number": "BRZ-SLV-400",
            "po_quantity": 30,
            "oar_number": oar_num,
            "create_wos": False,
        },
    )
    assert resp3.status_code == 400
    assert "already exists" in resp3.json()["detail"]

def test_auto_link_po_line_and_allocated_qty(client):
    """When creating OAR against a Customer PO, po_line_id is auto-linked even if omitted,
    and available_qty is deducted so the PO line drops from pending list."""
    token = _login(client, "PLANNING")
    headers = _auth(token)
    po_num = f"PO-AUTOLINK-{uuid.uuid4().hex[:6]}"

    # Create a PO Master with 2 lines
    po_resp = client.post(
        "/api/v1/masters/pos",
        headers=headers,
        json={
            "customer_code": "CUST-VALVE",
            "po_number": po_num,
            "po_date": "2026-09-01",
            "lines": [
                {"part_number": "BRZ-BUSH-100", "po_qty": 100, "required_date": "2026-10-15"},
                {"part_number": "BRZ-GEAR-150", "po_qty": 200, "required_date": "2026-10-20"},
            ],
        },
    )
    assert po_resp.status_code == 200, po_resp.text
    po_data = po_resp.json()
    line1_id = po_data["lines"][0]["id"]

    # Intake for line 1 WITHOUT explicitly providing po_line_id
    sales_headers = _auth(_login(client, "SALES"))
    intake_resp = client.post(
        "/api/v1/operations/intake",
        headers=sales_headers,
        json={
            "customer_code": "CUST-VALVE",
            "customer_name": "Flowserve Controls Ltd",
            "customer_po": po_num,
            "part_number": "BRZ-BUSH-100",
            "po_quantity": 100,
            "commitment_date": "2026-10-15",
            "create_wos": False,
        },
    )
    assert intake_resp.status_code == 200, intake_resp.text

    # Re-fetch PO Master: line 1 available_qty should now be 0 (allocated=100), line 2 still 200
    refetch = client.get("/api/v1/masters/pos", headers=headers)
    assert refetch.status_code == 200
    matching_pos = [p for p in refetch.json() if p["po_number"] == po_num]
    assert len(matching_pos) == 1
    lines = matching_pos[0]["lines"]
    l1 = [l for l in lines if l["part_number"] == "BRZ-BUSH-100"][0]
    l2 = [l for l in lines if l["part_number"] == "BRZ-GEAR-150"][0]
    assert l1["available_qty"] == 0
    assert l1["allocated_qty"] == 100
    assert l2["available_qty"] == 200
    assert l2["allocated_qty"] == 0
