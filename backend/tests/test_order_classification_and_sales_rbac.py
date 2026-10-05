"""Regression tests for:
1. Order Type (REGULAR vs NPD) on Order Intake -- persisted on Order.order_classification.
2. Sales RBAC on Order Creation -- confirms the existing PLANNING_ROLES gate (already in
   place before this task) denies SALES and allows ADMIN/PLANNER, via direct HTTP calls
   (never just checking a frontend nav entry), covering both Order Intake (OAR creation)
   and PO Master creation.

Uses TestClient(app) against the app's actually-configured database, matching the
established pattern in tests/test_po_schedule_master_data.py -- never Neon/production.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
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


def _login(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _unique(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture
def sales_login():
    """No seeded Sales login exists -- create one ad-hoc, directly via the same
    hash_password() the real registration path uses, matching the established
    direct-DB-insert pattern other test files already use for non-seeded roles."""
    db = SessionLocal()
    email = f"sales-{uuid.uuid4().hex[:8]}@vspl.com"
    password = "SalesTest123!"
    user = User(
        full_name="Test Sales User", email=email,
        hashed_password=hash_password(password), role=UserRole.SALES, is_active=True,
    )
    db.add(user)
    db.commit()
    db.close()
    return email, password


@pytest.fixture
def planner_login():
    """No seeded Planner login exists either -- same ad-hoc creation."""
    db = SessionLocal()
    email = f"planner-{uuid.uuid4().hex[:8]}@vspl.com"
    password = "PlannerTest123!"
    user = User(
        full_name="Test Planner User", email=email,
        hashed_password=hash_password(password), role=UserRole.PLANNER, is_active=True,
    )
    db.add(user)
    db.commit()
    db.close()
    return email, password


def _create_customer(client, headers, code=None):
    code = code or _unique("CUST")
    resp = client.post(
        "/api/v1/masters/customers", headers=headers,
        json={"customer_code": code, "name": f"Test Customer {code}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Order Type (REGULAR / NPD)
# ---------------------------------------------------------------------------

def test_order_intake_defaults_to_regular_when_omitted(client):
    headers = _auth(_login(client, *SEEDED_LOGINS["ADMIN"]))
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Flowserve Controls Ltd",
            "customer_po": f"PO-OT-{uuid.uuid4().hex[:8]}", "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["order_classification"] == "regular"


def test_order_intake_npd_is_persisted_and_returned(client):
    headers = _auth(_login(client, *SEEDED_LOGINS["ADMIN"]))
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Flowserve Controls Ltd",
            "customer_po": f"PO-OT-{uuid.uuid4().hex[:8]}", "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10, "order_classification": "npd",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["order_classification"] == "npd"


def test_order_intake_npd_appears_in_oar_list(client):
    headers = _auth(_login(client, *SEEDED_LOGINS["ADMIN"]))
    po_ref = f"PO-OT-LIST-{uuid.uuid4().hex[:8]}"
    create_resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Flowserve Controls Ltd",
            "customer_po": po_ref, "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10, "order_classification": "npd",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    oar_number = create_resp.json()["oar_number"]

    list_resp = client.get("/api/v1/operations/oars", headers=headers, params={"search": oar_number})
    assert list_resp.status_code == 200, list_resp.text
    matching = [o for o in list_resp.json() if o["oar_number"] == oar_number]
    assert len(matching) == 1
    assert matching[0]["order_classification"] == "npd"


def test_invalid_order_classification_rejected(client):
    headers = _auth(_login(client, *SEEDED_LOGINS["ADMIN"]))
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Flowserve Controls Ltd",
            "customer_po": f"PO-OT-{uuid.uuid4().hex[:8]}", "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10, "order_classification": "not-a-real-value",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Sales RBAC on Order Creation -- Order Intake and PO Master
# ---------------------------------------------------------------------------

def test_sales_cannot_create_order_intake(client, sales_login):
    headers = _auth(_login(client, *sales_login))
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Flowserve Controls Ltd",
            "customer_po": f"PO-SALES-{uuid.uuid4().hex[:8]}", "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10,
        },
    )
    assert resp.status_code == 403, resp.text


def test_sales_cannot_create_po_master(client, sales_login):
    headers = _auth(_login(client, *sales_login))
    resp = client.post(
        "/api/v1/masters/pos", headers=headers,
        json={"po_number": f"PO-SALES-{uuid.uuid4().hex[:8]}", "customer_code": "CUST-VALVE",
              "lines": [{"part_number": "BRZ-BUSH-100", "po_qty": 5}]},
    )
    assert resp.status_code == 403, resp.text


def test_sales_cannot_create_customer_master(client, sales_login):
    headers = _auth(_login(client, *sales_login))
    resp = client.post(
        "/api/v1/masters/customers", headers=headers,
        json={"customer_code": _unique("SALESCUST"), "name": "Attempted by Sales"},
    )
    assert resp.status_code == 403, resp.text


def test_sales_cannot_confirm_po_schedule_match(client, sales_login):
    headers = _auth(_login(client, *sales_login))
    resp = client.post(
        "/api/v1/po-matching/match", headers=headers,
        json={"po_line_id": str(uuid.uuid4()), "schedule_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403, resp.text


def test_sales_denied_regardless_of_request_shape(client, sales_login):
    """Not just the documented JSON shape -- an arbitrary/malformed body must still hit
    the 403 role check before any validation or business logic runs."""
    headers = _auth(_login(client, *sales_login))
    resp = client.post("/api/v1/operations/intake", headers=headers, json={})
    assert resp.status_code == 403, resp.text


def test_planner_can_create_order_intake(client, planner_login):
    """The role legitimately responsible for Order Creation must retain access."""
    headers = _auth(_login(client, *planner_login))
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Flowserve Controls Ltd",
            "customer_po": f"PO-PLANNER-{uuid.uuid4().hex[:8]}", "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10,
        },
    )
    assert resp.status_code == 200, resp.text


def test_admin_can_create_order_intake(client):
    headers = _auth(_login(client, *SEEDED_LOGINS["ADMIN"]))
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Flowserve Controls Ltd",
            "customer_po": f"PO-ADMIN-{uuid.uuid4().hex[:8]}", "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10,
        },
    )
    assert resp.status_code == 200, resp.text


def test_unauthenticated_request_to_order_intake_rejected(client):
    resp = client.post(
        "/api/v1/operations/intake",
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Flowserve Controls Ltd",
            "customer_po": f"PO-ANON-{uuid.uuid4().hex[:8]}", "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10,
        },
    )
    assert resp.status_code in (401, 403)
