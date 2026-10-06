"""Tests for FI -> PACKING -> BSR WIP Calculation and Zero Double-Counting Reconciliation.

Verifies:
1. Discrete PACKING and BSR stages: WIP is computed via independent sequential flow without double-counting.
2. In-Process (net) and On-Hand calculations at PACKING and BSR stages.
3. Quality Gate: Rejections at FI never enter PACKING/BSR.
4. Partial Packing, Partial Movement to BSR, and Partial Dispatch.
5. Work Order and Plant-wide Reconciliation: variance is strictly 0.
6. Combined PACKING / BSR routes backward-compatibility.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
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


def _unique(prefix="REC"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _setup_order_and_release(client, headers, qty=100, route_stages=None):
    if route_stages is None:
        route_stages = ["F1", "F2", "FI", "PACKING", "BSR", "DISPATCH"]
    cust_code = _unique("CUST")
    cust_name = f"Reconciliation Customer {cust_code}"
    part_num = f"PART-{uuid.uuid4().hex[:6].upper()}"

    c_resp = client.post(
        "/api/v1/masters/customers", headers=headers,
        json={"customer_code": cust_code, "name": cust_name}
    )
    assert c_resp.status_code == 200, c_resp.text

    po_num = _unique("PO")
    intake_resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": cust_code,
            "customer_name": cust_name,
            "customer_po": po_num,
            "part_number": part_num,
            "part_description": "Precision Bushing",
            "grade": "PB2",
            "po_quantity": qty,
            "max_batch_size": qty,
            "rate": 100.0,
            "order_type": "Direct Sales",
            "product_group": "Bronze Components"
        }
    )
    assert intake_resp.status_code == 200, intake_resp.text
    wo_num = intake_resp.json()["wos_created"][0]

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


def test_discrete_packing_bsr_sequential_wip_reconciliation(client):
    token = _login(client)
    headers = _auth(token)

    wo_num, cust_code, cust_name, part_num = _setup_order_and_release(
        client, headers, qty=100, route_stages=["F1", "F2", "FI", "PACKING", "BSR", "DISPATCH"]
    )

    # 1. Stage F1: Produce 100 Good
    f1_ent = client.post(
        "/api/v1/production/entry", headers=headers,
        json={"wo_number": wo_num, "stage": "F1", "good_qty": 100, "rejected_quantity": 0}
    )
    assert f1_ent.status_code == 200, f1_ent.text

    # Move F1 -> F2 (100)
    m1 = client.post(
        "/api/v1/production/move", headers=headers,
        json={"wo_number": wo_num, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 100}
    )
    assert m1.status_code == 200, m1.text

    # 2. Stage F2: Produce 100 Good
    f2_ent = client.post(
        "/api/v1/production/entry", headers=headers,
        json={"wo_number": wo_num, "stage": "F2", "good_qty": 100, "rejected_quantity": 0}
    )
    assert f2_ent.status_code == 200, f2_ent.text

    # Move F2 -> FI (100)
    m2 = client.post(
        "/api/v1/production/move", headers=headers,
        json={"wo_number": wo_num, "from_stage": "F2", "to_stage": "FI", "quantity_moved": 100}
    )
    assert m2.status_code == 200, m2.text

    # 3. Stage FI: 90 Good, 10 Rejected (NC recorded)
    fi_ent = client.post(
        "/api/v1/production/entry", headers=headers,
        json={"wo_number": wo_num, "stage": "FI", "good_qty": 90, "rejected_quantity": 10}
    )
    assert fi_ent.status_code == 200, fi_ent.text

    # Move FI -> PACKING (90 Good)
    m3 = client.post(
        "/api/v1/production/move", headers=headers,
        json={"wo_number": wo_num, "from_stage": "FI", "to_stage": "PACKING", "quantity_moved": 90}
    )
    assert m3.status_code == 200, m3.text

    # 4. PACKING stage: Pack 50 pieces (40 pending)
    pack_upd = client.post(
        "/api/v1/packing/update", headers=headers,
        json={"wo_number": wo_num, "packed_quantity": 50, "box_count": 5, "package_type": "Wooden Box"}
    )
    assert pack_upd.status_code == 200, pack_upd.text
    pack_data = pack_upd.json()
    assert pack_data["total_packed"] == 50
    assert pack_data["remaining_pending"] == 40

    # Check intermediate reconciliation:
    # WIP: PACKING inproc=40, onhand=50 -> Total WIP = 90. Rej = 10. Accounted = 100. Variance = 0.
    rec_resp = client.get("/api/v1/production/reconciliation", headers=headers)
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    wo_rec = next(r for r in rec_data["reconciliations"] if r["wo_number"] == wo_num)
    assert wo_rec["total_wip"] == 90
    assert wo_rec["total_rejected"] == 10
    assert wo_rec["dispatched_qty"] == 0
    assert wo_rec["variance"] == 0
    assert wo_rec["is_balanced"] is True

    # 5. Move PACKING -> BSR (50 packed pieces)
    m4 = client.post(
        "/api/v1/production/move", headers=headers,
        json={"wo_number": wo_num, "from_stage": "PACKING", "to_stage": "BSR", "quantity_moved": 50}
    )
    assert m4.status_code == 200, m4.text

    # Check reconciliation after moving to BSR:
    # WIP: PACKING has 40 inproc (onhand=0), BSR has 50 onhand (inproc=0). Total WIP = 90.
    rec_resp2 = client.get("/api/v1/production/reconciliation", headers=headers)
    assert rec_resp2.status_code == 200
    rec_data2 = rec_resp2.json()
    wo_rec2 = next(r for r in rec_data2["reconciliations"] if r["wo_number"] == wo_num)
    assert wo_rec2["total_wip"] == 90
    assert wo_rec2["variance"] == 0
    assert wo_rec2["is_balanced"] is True

    # 6. Dispatch: Dispatch 30 pieces from BSR
    inv_num = _unique("INV")
    disp_resp = client.post(
        "/api/v1/dispatch/ship", headers=headers,
        json={"wo_number": wo_num, "invoice_number": inv_num, "dispatched_quantity": 30}
    )
    assert disp_resp.status_code == 200, disp_resp.text

    # Check final reconciliation:
    # WIP: PACKING 40 + BSR 20 = 60. Rejections = 10. Dispatched = 30.
    # Total Accounted = 60 + 10 + 30 = 100. Released = 100. Variance = 0!
    rec_resp3 = client.get("/api/v1/production/reconciliation", headers=headers)
    assert rec_resp3.status_code == 200
    rec_data3 = rec_resp3.json()
    wo_rec3 = next(r for r in rec_data3["reconciliations"] if r["wo_number"] == wo_num)
    assert wo_rec3["total_wip"] == 60
    assert wo_rec3["total_rejected"] == 10
    assert wo_rec3["dispatched_qty"] == 30
    assert wo_rec3["accounted_qty"] == 100
    assert wo_rec3["variance"] == 0
    assert wo_rec3["is_balanced"] is True


def test_combined_packing_bsr_route_compatibility(client):
    token = _login(client)
    headers = _auth(token)

    wo_num, _, _, _ = _setup_order_and_release(
        client, headers, qty=60, route_stages=["F1", "F2", "FI", "PACKING / BSR", "DISPATCH"]
    )

    # 1. F1: 60 Good
    client.post("/api/v1/production/entry", headers=headers, json={"wo_number": wo_num, "stage": "F1", "good_qty": 60, "rejected_quantity": 0})
    client.post("/api/v1/production/move", headers=headers, json={"wo_number": wo_num, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 60})

    # 2. F2: 60 Good
    client.post("/api/v1/production/entry", headers=headers, json={"wo_number": wo_num, "stage": "F2", "good_qty": 60, "rejected_quantity": 0})
    client.post("/api/v1/production/move", headers=headers, json={"wo_number": wo_num, "from_stage": "F2", "to_stage": "FI", "quantity_moved": 60})

    # 3. FI: 60 Good
    client.post("/api/v1/production/entry", headers=headers, json={"wo_number": wo_num, "stage": "FI", "good_qty": 60, "rejected_quantity": 0})
    client.post("/api/v1/production/move", headers=headers, json={"wo_number": wo_num, "from_stage": "FI", "to_stage": "PACKING / BSR", "quantity_moved": 60})

    # 4. Pack 40
    pack_resp = client.post("/api/v1/packing/update", headers=headers, json={"wo_number": wo_num, "packed_quantity": 40})
    assert pack_resp.status_code == 200

    # 5. Dispatch 40
    inv = _unique("INV")
    disp_resp = client.post("/api/v1/dispatch/ship", headers=headers, json={"wo_number": wo_num, "invoice_number": inv, "dispatched_quantity": 40})
    assert disp_resp.status_code == 200

    # Check reconciliation
    rec_resp = client.get("/api/v1/production/reconciliation", headers=headers)
    assert rec_resp.status_code == 200
    wo_rec = next(r for r in rec_resp.json()["reconciliations"] if r["wo_number"] == wo_num)
    assert wo_rec["total_wip"] == 20
    assert wo_rec["dispatched_qty"] == 40
    assert wo_rec["variance"] == 0
    assert wo_rec["is_balanced"] is True
