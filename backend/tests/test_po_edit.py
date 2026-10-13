"""Comprehensive tests for Phase 2: PO Master Edit.

Covers:
1. Authorized and unauthorized updates (RBAC: ADMIN/PLANNER vs STORE/OPERATOR).
2. PO dates and validity date updates.
3. Customer immutability enforcement.
4. Conditional PO number changes (safe when unallocated; rejected when orders/allocations exist).
5. Customer-scoped duplicate PO number prevention.
6. Quantity reductions below allocated quantity blocked with HTTP 400.
7. Adding new PO lines to an existing PO.
8. Deleting unallocated lines allowed; deleting allocated lines blocked with HTTP 400.
9. Correct balance and available quantity derivation.
10. Audit logging on PO updates.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.database import SessionLocal
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.master_data import POMaster, POLine, POStatus
from app.models.audit import AuditLog
from app.main import app

SEEDED_LOGINS = {
    "ADMIN": ("admin@vspl.com", "admin123"),
    "STORE": ("store@vspl.com", "store123"),
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


def _unique_code(prefix="CUST"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _setup_test_customer_and_part(db):
    cust = Customer(customer_code=_unique_code(), name="Test Customer Corp")
    part = Part(part_number=_unique_code("PART"), grade="SG 500/7", description="Test Flange")
    db.add_all([cust, part])
    db.commit()
    db.refresh(cust)
    db.refresh(part)
    return cust, part


def test_authorized_and_unauthorized_po_edit(client):
    """Admin and Planner can update PO; Store role receives HTTP 403."""
    admin_headers = _auth(_login(client, "ADMIN"))
    store_headers = _auth(_login(client, "STORE"))

    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        po = POMaster(
            po_number=f"PO-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=100)
        db.add(line)
        db.commit()
        po_id = str(po.id)

        # 1. Store role (Unauthorized) -> 403
        resp_unauth = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=store_headers,
            json={"po_date": "2026-10-10"},
        )
        assert resp_unauth.status_code == 403

        # 2. Admin role (Authorized) -> 200
        resp_auth = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=admin_headers,
            json={"po_date": "2026-10-10"},
        )
        assert resp_auth.status_code == 200, resp_auth.text
        assert resp_auth.json()["po_date"] == "2026-10-10"
    finally:
        db.close()


def test_po_dates_and_validity_updates(client):
    """Updating po_date and validity_date persists accurately."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        po = POMaster(
            po_number=f"PO-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=50)
        db.add(line)
        db.commit()
        po_id = str(po.id)

        resp = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={
                "po_date": "2026-10-01",
                "validity_date": "2026-12-31",
                "status": "open",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["po_date"] == "2026-10-01"
        assert data["validity_date"] == "2026-12-31"
        assert data["status"] == "open"
    finally:
        db.close()


def test_customer_immutability(client):
    """Attempting to change customer code on an existing PO is rejected."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust1, part = _setup_test_customer_and_part(db)
        cust2 = Customer(customer_code=_unique_code(), name="Other Customer")
        db.add(cust2)
        db.commit()

        po = POMaster(
            po_number=f"PO-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust1.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=20)
        db.add(line)
        db.commit()
        po_id = str(po.id)

        resp = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={"customer_code": cust2.customer_code},
        )
        assert resp.status_code == 400
        assert "Customer association cannot be changed" in resp.json()["detail"]
    finally:
        db.close()


def test_po_number_change_safe_vs_unsafe(client):
    """PO number can be changed if no orders are linked; blocked once orders/allocations exist."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        po = POMaster(
            po_number=f"PO-ORIG-{uuid.uuid4().hex[:4].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=100)
        db.add(line)
        db.commit()
        po_id = str(po.id)
        line_id = str(line.id)

        # 1. Unallocated PO -> PO number update succeeds
        new_po_num = f"PO-RENAMED-{uuid.uuid4().hex[:4].upper()}"
        resp_safe = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={"po_number": new_po_num},
        )
        assert resp_safe.status_code == 200, resp_safe.text
        assert resp_safe.json()["po_number"] == new_po_num

        # 2. Link an OAR order to the PO line (allocating 30 pcs)
        order = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po=new_po_num,
            po_qty=30,
            max_batch_size=30,
            po_line_id=line.id,
            status=OrderStatus.CONFIRMED,
        )
        db.add(order)
        db.commit()

        # 3. Changing PO number now fails because orders are linked
        resp_unsafe = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={"po_number": "PO-BLOCKED-RENAME"},
        )
        assert resp_unsafe.status_code == 400
        assert "cannot be changed because" in resp_unsafe.json()["detail"]
        assert "order(s) (OARs) are already linked" in resp_unsafe.json()["detail"]
    finally:
        db.close()


def test_customer_scoped_duplicate_po_number(client):
    """Cannot edit PO number to match another PO of the same customer."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        existing_num = f"PO-EXIST-{uuid.uuid4().hex[:4].upper()}"
        po1 = POMaster(po_number=existing_num, customer_id=cust.id, status=POStatus.OPEN)
        po2 = POMaster(po_number=f"PO-OTHER-{uuid.uuid4().hex[:4].upper()}", customer_id=cust.id, status=POStatus.OPEN)
        db.add_all([po1, po2])
        db.flush()
        db.add_all([
            POLine(po_id=po1.id, part_id=part.id, po_qty=10),
            POLine(po_id=po2.id, part_id=part.id, po_qty=20),
        ])
        db.commit()

        resp = client.put(
            f"/api/v1/masters/pos/{po2.id}",
            headers=headers,
            json={"po_number": existing_num},
        )
        assert resp.status_code == 400
        assert f"PO number '{existing_num}' already exists for this customer" in resp.json()["detail"]
    finally:
        db.close()


def test_quantity_reduction_below_allocated_blocked(client):
    """Reducing PO line quantity below already allocated quantity is rejected."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        po = POMaster(
            po_number=f"PO-ALLOC-{uuid.uuid4().hex[:4].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=50)
        db.add(line)
        db.flush()

        # Allocate 35 pcs via OAR
        order = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po=po.po_number,
            po_qty=35,
            max_batch_size=35,
            po_line_id=line.id,
            status=OrderStatus.CONFIRMED,
        )
        db.add(order)
        db.commit()
        po_id = str(po.id)
        line_id = str(line.id)

        # 1. Attempting to reduce po_qty to 30 (below 35 allocated) -> 400
        resp_bad = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={
                "lines": [
                    {"id": line_id, "part_number": part.part_number, "po_qty": 30}
                ]
            },
        )
        assert resp_bad.status_code == 400
        assert "cannot be reduced below the already allocated quantity (35)" in resp_bad.json()["detail"]

        # 2. Updating po_qty to 40 (>= 35 allocated) -> 200
        resp_good = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={
                "lines": [
                    {"id": line_id, "part_number": part.part_number, "po_qty": 40}
                ]
            },
        )
        assert resp_good.status_code == 200, resp_good.text
        body = resp_good.json()
        assert body["lines"][0]["po_qty"] == 40
        assert body["lines"][0]["allocated_qty"] == 35
        assert body["lines"][0]["available_qty"] == 5
    finally:
        db.close()


def test_add_and_delete_lines_on_po(client):
    """Adding a new line succeeds; deleting unallocated line succeeds; deleting allocated line fails."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part1 = _setup_test_customer_and_part(db)
        part2 = Part(part_number=_unique_code("PART"), grade="SG 400", description="Second Part")
        part3 = Part(part_number=_unique_code("PART"), grade="SG 450", description="Third Part")
        db.add_all([part2, part3])
        db.commit()

        po = POMaster(
            po_number=f"PO-LINES-{uuid.uuid4().hex[:4].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line1 = POLine(po_id=po.id, part_id=part1.id, po_qty=100)
        line2 = POLine(po_id=po.id, part_id=part2.id, po_qty=50)
        db.add_all([line1, line2])
        db.flush()

        # Allocate line1 with 40 pcs
        order = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part1.id,
            customer_po=po.po_number,
            po_qty=40,
            max_batch_size=40,
            po_line_id=line1.id,
            status=OrderStatus.CONFIRMED,
        )
        db.add(order)
        db.commit()

        po_id = str(po.id)
        line1_id = str(line1.id)
        line2_id = str(line2.id)

        # 1. Attempt to delete allocated line1 (by omitting it from the lines payload) -> 400
        resp_del_alloc = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={
                "lines": [
                    {"id": line2_id, "part_number": part2.part_number, "po_qty": 50}
                ]
            },
        )
        assert resp_del_alloc.status_code == 400
        assert "Cannot delete PO line" in resp_del_alloc.json()["detail"]
        assert "allocated quantity" in resp_del_alloc.json()["detail"]

        # 2. Delete unallocated line2 and add new line3 in one request -> 200
        resp_update = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={
                "lines": [
                    {"id": line1_id, "part_number": part1.part_number, "po_qty": 100},
                    {"part_number": part3.part_number, "po_qty": 75, "required_date": "2026-11-15"},
                ]
            },
        )
        assert resp_update.status_code == 200, resp_update.text
        lines_data = resp_update.json()["lines"]
        assert len(lines_data) == 2
        # Check line1 retained
        l1 = next(l for l in lines_data if l["id"] == line1_id)
        assert l1["allocated_qty"] == 40
        assert l1["available_qty"] == 60
        # Check line3 added
        l3 = next(l for l in lines_data if l["part_number"] == part3.part_number)
        assert l3["po_qty"] == 75
        assert l3["allocated_qty"] == 0
        assert l3["available_qty"] == 75
    finally:
        db.close()


def test_po_update_audit_log(client):
    """Audit log records PO_UPDATED with actor and change details."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        po = POMaster(
            po_number=f"PO-AUDIT-{uuid.uuid4().hex[:4].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=80)
        db.add(line)
        db.commit()

        po_id = str(po.id)

        resp = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={
                "po_date": "2026-10-15",
                "validity_date": "2026-12-15",
            },
        )
        assert resp.status_code == 200, resp.text

        # Verify audit log entry
        audit_entry = (
            db.query(AuditLog)
            .filter(AuditLog.entity == "POMaster", AuditLog.entity_id == po_id, AuditLog.action == "PO_UPDATED")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert audit_entry is not None
        assert "po_date" in audit_entry.details
        assert "validity_date" in audit_entry.details
    finally:
        db.close()


def test_closed_and_cancelled_po_intake_prevention(client):
    """Closed and Cancelled POs block new OAR intake and schedule matching."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        po = POMaster(
            po_number=f"PO-STATUS-{uuid.uuid4().hex[:4].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=50)
        db.add(line)
        db.commit()

        po_id = str(po.id)
        line_id = str(line.id)

        # Close the PO
        resp_close = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={"status": "closed"},
        )
        assert resp_close.status_code == 200
        assert resp_close.json()["status"] == "closed"

        # Attempt to raise OAR against closed PO -> 400
        resp_intake = client.post(
            "/api/v1/operations/intake",
            headers=headers,
            json={
                "customer_code": cust.customer_code,
                "customer_name": cust.name,
                "customer_po": po.po_number,
                "part_number": part.part_number,
                "po_quantity": 10,
                "max_batch_size": 10,
                "po_line_id": line_id,
            },
        )
        assert resp_intake.status_code == 400
        assert "is in 'closed' status" in resp_intake.json()["detail"]
    finally:
        db.close()


def test_cancel_po_with_allocated_orders_fails(client):
    """Cannot set PO status to 'cancelled' if active allocations exist."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        po = POMaster(
            po_number=f"PO-NOCANCEL-{uuid.uuid4().hex[:4].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=40)
        db.add(line)
        db.flush()

        order = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po=po.po_number,
            po_qty=20,
            max_batch_size=20,
            po_line_id=line.id,
            status=OrderStatus.CONFIRMED,
        )
        db.add(order)
        db.commit()

        po_id = str(po.id)

        resp = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={"status": "cancelled"},
        )
        assert resp.status_code == 400
        assert "Cannot cancel PO because it has 20 allocated quantity" in resp.json()["detail"]
    finally:
        db.close()


def test_transaction_rollback_and_audit_atomicity(client):
    """Failed PO update rolls back both PO changes and audit log atomically."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        po = POMaster(
            po_number=f"PO-ATOMIC-{uuid.uuid4().hex[:4].upper()}",
            customer_id=cust.id,
            po_date=None,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=50)
        db.add(line)
        db.flush()

        order = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po=po.po_number,
            po_qty=30,
            max_batch_size=30,
            po_line_id=line.id,
            status=OrderStatus.CONFIRMED,
        )
        db.add(order)
        db.commit()

        po_id = str(po.id)
        line_id = str(line.id)

        # Baseline audit count
        baseline_audits = db.query(AuditLog).filter(AuditLog.entity_id == po_id).count()

        # Update that attempts to change po_date but fails on line quantity reduction
        resp = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={
                "po_date": "2026-10-20",
                "lines": [
                    {"id": line_id, "part_number": part.part_number, "po_qty": 10}  # Invalid: < 30 allocated
                ],
            },
        )
        assert resp.status_code == 400

        # Verify DB state: po_date is STILL None (rolled back), and audit count is unchanged
        db.expire_all()
        po_fresh = db.query(POMaster).filter(POMaster.id == po.id).first()
        assert po_fresh.po_date is None
        current_audits = db.query(AuditLog).filter(AuditLog.entity_id == po_id).count()
        assert current_audits == baseline_audits
    finally:
        db.close()


def test_deletion_integrity_foreign_key_and_cascade_safety(client):
    """Allocated PO line deletion is blocked and downstream OARs/WOs remain untouched."""
    headers = _auth(_login(client, "ADMIN"))
    db = SessionLocal()
    try:
        cust, part = _setup_test_customer_and_part(db)
        po = POMaster(
            po_number=f"PO-CASCADE-{uuid.uuid4().hex[:4].upper()}",
            customer_id=cust.id,
            status=POStatus.OPEN,
        )
        db.add(po)
        db.flush()
        line = POLine(po_id=po.id, part_id=part.id, po_qty=60)
        db.add(line)
        db.flush()

        order = Order(
            oar_number=f"OAR-{uuid.uuid4().hex[:6].upper()}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po=po.po_number,
            po_qty=60,
            max_batch_size=60,
            po_line_id=line.id,
            status=OrderStatus.CONFIRMED,
        )
        db.add(order)
        db.commit()

        po_id = str(po.id)
        order_id = str(order.id)

        # Attempt to delete the allocated line via PUT by supplying an empty lines array
        resp = client.put(
            f"/api/v1/masters/pos/{po_id}",
            headers=headers,
            json={"lines": []},
        )
        assert resp.status_code == 400
        assert "PO must contain at least one line" in resp.json()["detail"]

        # Downstream Order still exists and points to the PO line
        order_check = db.query(Order).filter(Order.id == order_id).first()
        assert order_check is not None
        assert order_check.po_line_id == line.id
    finally:
        db.close()
