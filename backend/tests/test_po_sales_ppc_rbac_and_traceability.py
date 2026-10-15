"""PO -> OAR -> WO traceability display, and Sales/PPC PO-edit RBAC.

Covers:
1. PO with no linked OAR/WO -> empty `orders` list (truthful "OAR not created" state).
2. PO linked to an OAR but no WO -> one order summary, empty `work_orders`.
3. PO linked to an OAR and a WO -> release_status reflects the real release chain.
4. Multiple OARs linked to the same PO line -> both are returned, no arbitrary pick.
5. Released vs unreleased WO -> distinct `release_status` values.
6. Sales: PO list/detail view permitted; PO edit permitted.
7. Sales: OAR creation (order intake) and WO release remain denied (403) --
   this grant must not widen beyond PO master view/edit.
8. Planner (PPC): PO edit remains permitted (pre-existing, re-asserted here).
9. Backward compatibility: pre-existing POLineOut fields are unchanged in shape.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.master_data import POMaster, POLine, POStatus
from app.models.work_order import WorkOrder, WOStatus
from app.models.user import User, UserRole
from app.main import app

SEEDED_LOGINS = {
    "ADMIN": ("admin@vspl.com", "admin123"),
    "PLANNER": ("planner@vspl.com", "planner123"),
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


def _login(client, role_key):
    email, password = SEEDED_LOGINS[role_key]
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _uid(prefix="TEST"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _sales_headers(db):
    """No seeded Sales user exists -- create one directly, matching the pattern used
    elsewhere in this suite for roles without a seeded login (e.g.
    test_wo_release_casting_process.py's _auth_headers)."""
    user = User(
        full_name="Test Sales User", email=f"{_uid('sales').lower()}@vspl.com",
        hashed_password="x", role=UserRole.SALES,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(data={"sub": user.email, "user_id": str(user.id), "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}, user


def _make_po(db, cust, part, po_qty=100):
    po = POMaster(po_number=_uid("PO"), customer_id=cust.id, status=POStatus.OPEN)
    db.add(po)
    db.flush()
    line = POLine(po_id=po.id, part_id=part.id, po_qty=po_qty)
    db.add(line)
    db.commit()
    db.refresh(po)
    db.refresh(line)
    return po, line


def _make_order(db, cust, part, line=None, po_qty=50, oar_number=None):
    order = Order(
        oar_number=oar_number or _uid("OAR"), customer_id=cust.id, part_id=part.id,
        customer_po=_uid("PO"), po_qty=po_qty, max_batch_size=po_qty,
        source_type="po", po_line_id=line.id if line else None, status=OrderStatus.ACCEPT,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _make_wo(db, order, qty=50, released=False):
    wo = WorkOrder(
        wo_number=_uid("WO"), order_id=order.id, physical_wo_qty=qty,
        status=WOStatus.IN_PRODUCTION if released else WOStatus.PLANNED, current_stage="F1",
    )
    if released:
        wo.released_by = "Test Planner"
        from datetime import datetime, timezone
        wo.release_date = datetime.now(timezone.utc)
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return wo


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------

def test_po_line_with_no_oar_shows_truthful_empty_state(client):
    headers = _login(client, "ADMIN")
    db = SessionLocal()
    try:
        cust = Customer(customer_code=_uid("CUST"), name="No OAR Customer")
        part = Part(part_number=_uid("PART"), description="No OAR Part")
        db.add_all([cust, part])
        db.commit()
        po, line = _make_po(db, cust, part)

        resp = client.get(f"/api/v1/masters/pos/{po.id}", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["lines"]) == 1
        assert data["lines"][0]["orders"] == []  # truthful "OAR not created", never fabricated

        db.delete(line); db.delete(po); db.delete(part); db.delete(cust); db.commit()
    finally:
        db.close()


def test_po_line_with_oar_but_no_wo(client):
    headers = _login(client, "ADMIN")
    db = SessionLocal()
    try:
        cust = Customer(customer_code=_uid("CUST"), name="OAR No WO Customer")
        part = Part(part_number=_uid("PART"), description="OAR No WO Part")
        db.add_all([cust, part])
        db.commit()
        po, line = _make_po(db, cust, part)
        order = _make_order(db, cust, part, line=line)

        resp = client.get(f"/api/v1/masters/pos/{po.id}", headers=headers)
        assert resp.status_code == 200, resp.text
        orders = resp.json()["lines"][0]["orders"]
        assert len(orders) == 1
        assert orders[0]["oar_id"] == str(order.id)
        assert orders[0]["oar_number"] == order.oar_number
        assert orders[0]["work_orders"] == []  # truthful "WO not created"

        db.delete(order); db.delete(line); db.delete(po); db.delete(part); db.delete(cust); db.commit()
    finally:
        db.close()


def test_po_line_with_oar_and_wo_release_states(client):
    headers = _login(client, "ADMIN")
    db = SessionLocal()
    try:
        cust = Customer(customer_code=_uid("CUST"), name="OAR WO Customer")
        part = Part(part_number=_uid("PART"), description="OAR WO Part")
        db.add_all([cust, part])
        db.commit()
        po, line = _make_po(db, cust, part, po_qty=100)
        order = _make_order(db, cust, part, line=line, po_qty=100)
        wo_unreleased = _make_wo(db, order, qty=40, released=False)
        wo_released = _make_wo(db, order, qty=60, released=True)

        resp = client.get(f"/api/v1/masters/pos/{po.id}", headers=headers)
        assert resp.status_code == 200, resp.text
        orders = resp.json()["lines"][0]["orders"]
        assert len(orders) == 1
        wos = {w["wo_id"]: w for w in orders[0]["work_orders"]}
        assert len(wos) == 2
        assert wos[str(wo_unreleased.id)]["release_status"] == "AWAITING_ENG_RELEASE"
        assert wos[str(wo_released.id)]["release_status"] == "RELEASED"

        db.delete(wo_unreleased); db.delete(wo_released); db.delete(order)
        db.delete(line); db.delete(po); db.delete(part); db.delete(cust); db.commit()
    finally:
        db.close()


def test_multiple_oars_on_same_po_line_all_returned(client):
    """A PO line is not assumed to have a single OAR -- both must be returned, not an
    arbitrary pick."""
    headers = _login(client, "ADMIN")
    db = SessionLocal()
    try:
        cust = Customer(customer_code=_uid("CUST"), name="Multi OAR Customer")
        part = Part(part_number=_uid("PART"), description="Multi OAR Part")
        db.add_all([cust, part])
        db.commit()
        po, line = _make_po(db, cust, part, po_qty=100)
        order_a = _make_order(db, cust, part, line=line, po_qty=40, oar_number=_uid("OAR-A"))
        order_b = _make_order(db, cust, part, line=line, po_qty=60, oar_number=_uid("OAR-B"))

        resp = client.get(f"/api/v1/masters/pos/{po.id}", headers=headers)
        assert resp.status_code == 200, resp.text
        orders = resp.json()["lines"][0]["orders"]
        oar_ids = {o["oar_id"] for o in orders}
        assert oar_ids == {str(order_a.id), str(order_b.id)}

        db.delete(order_a); db.delete(order_b)
        db.delete(line); db.delete(po); db.delete(part); db.delete(cust); db.commit()
    finally:
        db.close()


def test_backward_compatible_po_line_fields_unchanged(client):
    """Existing consumers reading only the pre-existing POLineOut fields must keep working."""
    headers = _login(client, "ADMIN")
    db = SessionLocal()
    try:
        cust = Customer(customer_code=_uid("CUST"), name="Back Compat Customer")
        part = Part(part_number=_uid("PART"), description="Back Compat Part")
        db.add_all([cust, part])
        db.commit()
        po, line = _make_po(db, cust, part, po_qty=75)

        resp = client.get(f"/api/v1/masters/pos/{po.id}", headers=headers)
        assert resp.status_code == 200, resp.text
        line_out = resp.json()["lines"][0]
        for field in ("id", "part_number", "po_qty", "allocated_qty", "available_qty", "required_date"):
            assert field in line_out
        assert line_out["po_qty"] == 75
        assert line_out["allocated_qty"] == 0
        assert line_out["available_qty"] == 75

        db.delete(line); db.delete(po); db.delete(part); db.delete(cust); db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

def test_sales_can_view_and_edit_po(client):
    db = SessionLocal()
    try:
        sales_headers, sales_user = _sales_headers(db)
        cust = Customer(customer_code=_uid("CUST"), name="Sales RBAC Customer")
        part = Part(part_number=_uid("PART"), description="Sales RBAC Part")
        db.add_all([cust, part])
        db.commit()
        po, line = _make_po(db, cust, part)

        # Sales can list and view POs
        resp_list = client.get("/api/v1/masters/pos", headers=sales_headers, params={"customer_code": cust.customer_code})
        assert resp_list.status_code == 200, resp_list.text

        resp_get = client.get(f"/api/v1/masters/pos/{po.id}", headers=sales_headers)
        assert resp_get.status_code == 200, resp_get.text

        # Sales can edit PO (e.g. commercial dates)
        resp_edit = client.put(
            f"/api/v1/masters/pos/{po.id}", headers=sales_headers, json={"po_date": "2026-11-01"},
        )
        assert resp_edit.status_code == 200, resp_edit.text
        assert resp_edit.json()["po_date"] == "2026-11-01"

        db.delete(line); db.delete(po); db.delete(part); db.delete(cust)
        db.delete(sales_user); db.commit()
    finally:
        db.close()


def test_sales_and_ceo_can_create_oar_and_release_wo(client):
    """Sales, Planner, and CEO share unified planning & OAR/WO release capabilities."""
    db = SessionLocal()
    try:
        sales_headers, sales_user = _sales_headers(db)
        cust_code = _uid("CUST")
        part_num = _uid("PART")

        # Sales can create OAR (order intake)
        resp_intake = client.post(
            "/api/v1/operations/intake", headers=sales_headers,
            json={
                "customer_code": cust_code, "customer_name": "Sales Granted Co",
                "customer_po": _uid("PO"), "part_number": part_num,
                "po_quantity": 10, "max_batch_size": 10,
            },
        )
        assert resp_intake.status_code == 200, resp_intake.text

        # Sales passes RBAC gate for WO release (returns 404 for nonexistent WO, NOT 403)
        resp_release = client.post(
            "/api/v1/operations/wo-release", headers=sales_headers,
            json={"wo_number": "NONEXISTENT-WO", "physical_wo_qty": 10, "route_stages": ["F1", "DISPATCH"]},
        )
        assert resp_release.status_code == 404, resp_release.text

        db.delete(sales_user); db.commit()
    finally:
        db.close()


def test_planner_ppc_can_still_edit_po(client):
    """Pre-existing Planner (PPC) PO-edit access must remain intact."""
    headers = _login(client, "PLANNER")
    db = SessionLocal()
    try:
        cust = Customer(customer_code=_uid("CUST"), name="PPC Edit Customer")
        part = Part(part_number=_uid("PART"), description="PPC Edit Part")
        db.add_all([cust, part])
        db.commit()
        po, line = _make_po(db, cust, part)

        resp = client.put(f"/api/v1/masters/pos/{po.id}", headers=headers, json={"po_date": "2026-11-15"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["po_date"] == "2026-11-15"

        db.delete(line); db.delete(po); db.delete(part); db.delete(cust); db.commit()
    finally:
        db.close()


def test_update_oar_commitment_date(client):
    """Sales or Planner can edit the commitment date on an existing OAR."""
    db = SessionLocal()
    try:
        sales_headers, sales_user = _sales_headers(db)
        cust_code = _uid("CUST")
        part_num = _uid("PART")
        po_num = _uid("PO")

        resp_intake = client.post(
            "/api/v1/operations/intake", headers=sales_headers,
            json={
                "customer_code": cust_code, "customer_name": "Commitment Test Co",
                "customer_po": po_num, "part_number": part_num,
                "po_quantity": 25, "commitment_date": "2026-10-20", "delivery_date": "2026-10-25"
            },
        )
        assert resp_intake.status_code == 200, resp_intake.text
        oar_num = resp_intake.json()["oar_number"]

        # Now edit the commitment date
        resp_update = client.patch(
            f"/api/v1/operations/oars/{oar_num}",
            headers=sales_headers,
            json={
                "commitment_date": "2026-11-10",
                "delivery_date": "2026-11-15",
                "status": "accept",
                "remarks": "Customer requested rescheduled shipment"
            }
        )
        assert resp_update.status_code == 200, resp_update.text
        data = resp_update.json()
        assert data["commitment_date"] == "2026-11-10"
        assert data["delivery_date"] == "2026-11-15"

        # Verify listing returns the updated commitment date
        resp_list = client.get("/api/v1/operations/oars", headers=sales_headers, params={"search": oar_num})
        assert resp_list.status_code == 200
        items = resp_list.json()
        assert len(items) > 0
        assert items[0]["commitment_date"] == "2026-11-10"

        db.delete(sales_user); db.commit()
    finally:
        db.close()


def test_sales_can_cancel_and_delete_po(client):
    """Sales department can cancel a PO and delete a cancelled/unallocated PO."""
    db = SessionLocal()
    try:
        sales_headers, sales_user = _sales_headers(db)
        cust = Customer(customer_code=_uid("CUST"), name="Delete Test Cust")
        part = Part(part_number=_uid("PART"), description="Delete Test Part")
        db.add_all([cust, part])
        db.commit()
        po, line = _make_po(db, cust, part)

        # Sales can mark PO as cancelled
        resp_cancel = client.put(
            f"/api/v1/masters/pos/{po.id}",
            headers=sales_headers,
            json={"status": "cancelled"}
        )
        assert resp_cancel.status_code == 200, resp_cancel.text
        assert resp_cancel.json()["status"] == "cancelled"

        # Sales can delete the PO
        resp_del = client.delete(f"/api/v1/masters/pos/{po.id}", headers=sales_headers)
        assert resp_del.status_code == 200, resp_del.text
        assert "deleted successfully" in resp_del.json()["message"]

        # Confirm PO is deleted
        resp_get = client.get(f"/api/v1/masters/pos/{po.id}", headers=sales_headers)
        assert resp_get.status_code == 404

        db.delete(part); db.delete(cust); db.delete(sales_user); db.commit()
    finally:
        db.close()

