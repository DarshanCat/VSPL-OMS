"""Tests for Heat Number Management and Traceability.

Verifies:
1. Heat creation and validation (duplicate rejection, active status).
2. Heat allocation to Work Orders (M:N mapping).
3. F1 production entry with heat allocation.
4. Validation: sum of allocated heat quantities must equal processed quantity.
5. Quarantined heat cannot be allocated.
6. Full end-to-end Work Order traceability endpoint.
"""
import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.database import SessionLocal
from app.models.work_order import WorkOrder
from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client, email="admin@vspl.com", password="admin123"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _unique(prefix="HT"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _setup_order_and_release(client, headers, qty=100, route_stages=None):
    if route_stages is None:
        route_stages = ["F1", "F2", "FI", "PACKING / BSR", "DISPATCH"]
    cust_code = _unique("CUST")
    cust_name = f"Traceability Customer {cust_code}"
    part_num = f"PART-{uuid.uuid4().hex[:6].upper()}"

    # 1. Create customer
    c_resp = client.post(
        "/api/v1/masters/customers", headers=headers,
        json={"customer_code": cust_code, "name": cust_name}
    )
    assert c_resp.status_code == 200, c_resp.text

    # 2. Intake
    po_num = _unique("PO")
    intake_resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": cust_code,
            "customer_name": cust_name,
            "customer_po": po_num,
            "part_number": part_num,
            "part_description": "Machined Bushing",
            "grade": "PB2 / Bronze",
            "po_quantity": qty,
            "max_batch_size": qty,
            "rate": 250.0,
            "order_type": "Direct Sales",
            "product_group": "Bronze Components"
        }
    )
    assert intake_resp.status_code == 200, intake_resp.text
    wo_num = intake_resp.json()["wos_created"][0]

    # Stamp engineering and manufacturing release prerequisite
    db = SessionLocal()
    wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
    if wo:
        wo.engineering_released_by = "Lead Engineer"
        wo.engineering_released_at = datetime.now(timezone.utc)
        wo.manufacturing_released_by = "Mfg Lead"
        wo.manufacturing_released_at = datetime.now(timezone.utc)
        db.commit()
    db.close()

    # 3. Release WO
    rel_resp = client.post(
        "/api/v1/operations/wo-release", headers=headers,
        json={
            "wo_number": wo_num,
            "physical_wo_qty": qty,
            "route_stages": route_stages
        }
    )
    assert rel_resp.status_code == 200, rel_resp.text
    return wo_num, cust_code, cust_name, part_num


def test_heat_creation_and_listing(client):
    token = _login(client)
    headers = _auth(token)
    heat_no = _unique("HEAT")

    # 1. Create Heat
    resp = client.post(
        "/api/v1/heats", headers=headers,
        json={
            "heat_number": heat_no,
            "grade": "PB2",
            "melt_date": "2026-10-06",
            "status": "ACTIVE",
            "tc_number": "TC-2026-9901",
            "supplier_or_foundry": "Foundry Furnace Cell 1",
            "remarks": "Virgin melt certified"
        }
    )
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    assert data["heat_number"] == heat_no
    assert data["grade"] == "PB2"
    assert data["status"] == "ACTIVE"
    assert data["tc_number"] == "TC-2026-9901"

    # 2. Duplicate creation rejected
    dup_resp = client.post(
        "/api/v1/heats", headers=headers,
        json={"heat_number": heat_no, "grade": "PB2"}
    )
    assert dup_resp.status_code == 400

    # 3. List Heats
    list_resp = client.get(f"/api/v1/heats?search={heat_no}", headers=headers)
    assert list_resp.status_code == 200
    heats = list_resp.json()
    assert len(heats) >= 1
    assert any(h["heat_number"] == heat_no for h in heats)


def test_f1_production_entry_with_heat_allocations(client):
    token = _login(client)
    headers = _auth(token)

    wo_num, cust_code, cust_name, part_num = _setup_order_and_release(client, headers, qty=100)

    # Create two heats
    heat1 = _unique("H1")
    heat2 = _unique("H2")
    client.post("/api/v1/heats", headers=headers, json={"heat_number": heat1, "grade": "PB2"})
    client.post("/api/v1/heats", headers=headers, json={"heat_number": heat2, "grade": "PB2"})

    # 1. F1 production entry with heat allocations (60 pcs heat1, 40 pcs heat2 = 100 total)
    entry_resp = client.post(
        "/api/v1/production/entry", headers=headers,
        json={
            "wo_number": wo_num,
            "stage": "F1",
            "good_qty": 95,
            "rejected_quantity": 5,
            "operator_name": "Melt Tech",
            "heat_allocations": [
                {"heat_number": heat1, "allocated_qty": 60},
                {"heat_number": heat2, "allocated_qty": 40}
            ]
        }
    )
    assert entry_resp.status_code == 200, entry_resp.text
    entry_data = entry_resp.json()
    assert entry_data["good_qty"] == 95
    assert entry_data["rejected_quantity"] == 5

    # 2. Check WO Traceability
    tr_resp = client.get(f"/api/v1/work-orders/{wo_num}/traceability", headers=headers)
    assert tr_resp.status_code == 200, tr_resp.text
    tr_data = tr_resp.json()
    assert tr_data["wo_number"] == wo_num
    assert tr_data["total_heat_allocated_qty"] == 100
    assert len(tr_data["heats"]) == 2
    heat_nos = {h["heat_number"] for h in tr_data["heats"]}
    assert heat1 in heat_nos
    assert heat2 in heat_nos


def test_heat_allocation_mismatch_and_quarantine_validation(client):
    token = _login(client)
    headers = _auth(token)

    wo_num, _, _, _ = _setup_order_and_release(client, headers, qty=50)

    active_heat = _unique("H-ACT")
    quar_heat = _unique("H-QUAR")
    client.post("/api/v1/heats", headers=headers, json={"heat_number": active_heat, "grade": "PB2", "status": "ACTIVE"})
    client.post("/api/v1/heats", headers=headers, json={"heat_number": quar_heat, "grade": "PB2", "status": "QUARANTINED"})

    # 1. Mismatch quantity: 50 good + 0 rej = 50 processed, but allocating 40 -> 400
    bad_qty_resp = client.post(
        "/api/v1/production/entry", headers=headers,
        json={
            "wo_number": wo_num,
            "stage": "F1",
            "good_qty": 50,
            "rejected_quantity": 0,
            "heat_allocations": [
                {"heat_number": active_heat, "allocated_qty": 40}
            ]
        }
    )
    assert bad_qty_resp.status_code == 400
    assert "must equal total stage processed quantity" in bad_qty_resp.json()["detail"]

    # 2. Quarantined heat rejected
    quar_resp = client.post(
        "/api/v1/production/entry", headers=headers,
        json={
            "wo_number": wo_num,
            "stage": "F1",
            "good_qty": 50,
            "rejected_quantity": 0,
            "heat_allocations": [
                {"heat_number": quar_heat, "allocated_qty": 50}
            ]
        }
    )
    assert quar_resp.status_code == 400
    assert "QUARANTINED" in quar_resp.json()["detail"]


def test_single_heat_multiple_wos(client):
    token = _login(client)
    headers = _auth(token)

    wo_a, _, _, _ = _setup_order_and_release(client, headers, qty=50)
    wo_b, _, _, _ = _setup_order_and_release(client, headers, qty=50)

    shared_heat = _unique("H-SHARED")
    h_resp = client.post(
        "/api/v1/heats", headers=headers,
        json={"heat_number": shared_heat, "grade": "PB2", "status": "ACTIVE"}
    )
    assert h_resp.status_code in (200, 201)

    # 1. Allocate shared heat to WO-A
    ent_a = client.post(
        "/api/v1/production/entry", headers=headers,
        json={
            "wo_number": wo_a,
            "stage": "F1",
            "good_qty": 50,
            "rejected_quantity": 0,
            "heat_allocations": [{"heat_number": shared_heat, "allocated_qty": 50}]
        }
    )
    assert ent_a.status_code == 200, ent_a.text

    # 2. Allocate same shared heat to WO-B
    ent_b = client.post(
        "/api/v1/production/entry", headers=headers,
        json={
            "wo_number": wo_b,
            "stage": "F1",
            "good_qty": 50,
            "rejected_quantity": 0,
            "heat_allocations": [{"heat_number": shared_heat, "allocated_qty": 50}]
        }
    )
    assert ent_b.status_code == 200, ent_b.text

    # 3. Verify each WO has its own allocation
    tr_a = client.get(f"/api/v1/work-orders/{wo_a}/traceability", headers=headers).json()
    assert tr_a["total_heat_allocated_qty"] == 50
    assert len(tr_a["heats"]) == 1
    assert tr_a["heats"][0]["heat_number"] == shared_heat

    tr_b = client.get(f"/api/v1/work-orders/{wo_b}/traceability", headers=headers).json()
    assert tr_b["total_heat_allocated_qty"] == 50
    assert len(tr_b["heats"]) == 1
    assert tr_b["heats"][0]["heat_number"] == shared_heat

    # 4. Verify Heat aggregate reflects both allocations
    h_list = client.get(f"/api/v1/heats?search={shared_heat}", headers=headers).json()
    assert len(h_list) >= 1
    heat_item = next(h for h in h_list if h["heat_number"] == shared_heat)
    assert heat_item["total_allocated_qty"] == 100


def test_duplicate_f1_production_retry_with_heat_allocations(client):
    token = _login(client)
    headers = _auth(token)

    wo_num, _, _, _ = _setup_order_and_release(client, headers, qty=100)

    retry_heat = _unique("H-RETRY")
    client.post(
        "/api/v1/heats", headers=headers,
        json={"heat_number": retry_heat, "grade": "PB2", "status": "ACTIVE"}
    )

    client_req_id = _unique("REQ-F1")
    payload = {
        "client_request_id": client_req_id,
        "wo_number": wo_num,
        "stage": "F1",
        "good_qty": 60,
        "rejected_quantity": 0,
        "operator_name": "Foundry Tech",
        "heat_allocations": [{"heat_number": retry_heat, "allocated_qty": 60}]
    }

    # 1. First submission succeeds
    resp1 = client.post("/api/v1/production/entry", headers=headers, json=payload)
    assert resp1.status_code == 200, resp1.text
    data1 = resp1.json()
    assert data1["good_qty"] == 60
    assert data1["stage_ok_total"] == 60
    entry_id = data1["entry_id"]

    # Check traceability & stage WIP after 1st call
    tr1 = client.get(f"/api/v1/work-orders/{wo_num}/traceability", headers=headers).json()
    assert tr1["total_heat_allocated_qty"] == 60
    assert len(tr1["heats"]) == 1

    # 2. Retry with the EXACT SAME client_request_id
    resp2 = client.post("/api/v1/production/entry", headers=headers, json=payload)
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2["entry_id"] == entry_id
    assert "Duplicate production entry detected" in data2["message"]

    # 3. Verify no duplicate allocation rows and no quantity increase
    tr2 = client.get(f"/api/v1/work-orders/{wo_num}/traceability", headers=headers).json()
    assert tr2["total_heat_allocated_qty"] == 60
    assert len(tr2["heats"]) == 1

    # Stage WIP must remain exactly 60 OK, 40 unprocessed (out of 100)
    f1_prog = next(p for p in tr2["stage_progression"] if p["stage"] == "F1")
    assert f1_prog["ok_qty"] == 60
    assert f1_prog["inproc_qty"] == 40

