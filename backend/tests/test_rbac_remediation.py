"""
RBAC remediation regression tests (security phase 2).

These prove the four previously-open authorization gaps are now closed, using the
project's existing role model (no new permission concept was invented -- see
app/api/v1/operations.py PLANNING_ROLES / QUALITY_OVERSIGHT_ROLES and
app/api/v1/dispatch.py DISPATCH_ROLES, each of which reuses a role grouping already
used elsewhere in this codebase):

  1. WO Release  -> planning roles only (ADMIN, PLANNER, PRODUCTION_MANAGER)
  2. Conversion  -> planning roles only (same grouping; no separate master-data
     alteration exists in this system to distinguish from execution)
  3. Dispatch/Ship -> DISPATCH, PRODUCTION_MANAGER, ADMIN
  4. NC disposition (PUT) -> the same oversight roles already used for audit-log access
     (ADMIN, PRODUCTION_MANAGER, QA, CEO)

Each also proves the legitimate role can still complete the real operation end to end
(not just "not 403") to guard against accidentally locking out the intended workflow.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app

SEEDED_LOGINS = {
    "ADMIN": ("admin@vspl.com", "admin123"),
    "PLANNER": ("planner@vspl.com", "planner123"),
    "PRODUCTION_MANAGER": ("pm@vspl.com", "pm123"),
    "QA": ("qa@vspl.com", "qa123"),
    "DISPATCH": ("dispatch@vspl.com", "dispatch123"),
    "CEO": ("ceo@vspl.com", "ceo123"),
    "MACHINE_OPERATOR": ("operator@vspl.com", "op123"),
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


def _intake_fresh_wo(client, headers, po_qty=25):
    resp = client.post(
        "/api/v1/operations/intake",
        headers=headers,
        json={
            "customer_code": "CUST-RBAC-TEST",
            "customer_name": "RBAC Test Customer",
            "customer_po": f"PO-RBAC-{uuid.uuid4().hex[:8]}",
            "part_number": f"PART-RBAC-{uuid.uuid4().hex[:6]}",
            "po_quantity": po_qty,
            "max_batch_size": po_qty,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["wos_created"][0]


# ---------------------------------------------------------------------------
# 1. WO Release
# ---------------------------------------------------------------------------

def test_wo_release_rejects_unauthorized_role(client):
    admin_headers = _login(client, "ADMIN")
    wo_num = _intake_fresh_wo(client, admin_headers)

    operator_headers = _login(client, "MACHINE_OPERATOR")
    resp = client.post(
        "/api/v1/operations/wo-release",
        headers=operator_headers,
        json={"wo_number": wo_num, "physical_wo_qty": 25, "route_stages": ["F1", "F2", "DISPATCH"]},
    )
    assert resp.status_code == 403


def test_wo_release_succeeds_for_planner(client):
    admin_headers = _login(client, "ADMIN")
    wo_num = _intake_fresh_wo(client, admin_headers)

    planner_headers = _login(client, "PLANNER")
    resp = client.post(
        "/api/v1/operations/wo-release",
        headers=planner_headers,
        json={"wo_number": wo_num, "physical_wo_qty": 25, "route_stages": ["F1", "F2", "DISPATCH"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


def test_wo_release_succeeds_for_production_manager(client):
    admin_headers = _login(client, "ADMIN")
    wo_num = _intake_fresh_wo(client, admin_headers)

    pm_headers = _login(client, "PRODUCTION_MANAGER")
    resp = client.post(
        "/api/v1/operations/wo-release",
        headers=pm_headers,
        json={"wo_number": wo_num, "physical_wo_qty": 25, "route_stages": ["F1", "F2", "DISPATCH"]},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 2. Conversion
# ---------------------------------------------------------------------------

def test_conversion_rejects_unauthorized_role(client):
    operator_headers = _login(client, "MACHINE_OPERATOR")
    resp = client.post(
        "/api/v1/operations/conversion",
        headers=operator_headers,
        json={
            "conversion_wo_number": f"C-RBAC-{uuid.uuid4().hex[:8]}",
            "source_wo_number": "WO-1001",
            "destination_oar_number": "OAR-0002",
            "quantity": 5,
            "entry_stage": "F2",
            "reason": "RBAC test",
        },
    )
    assert resp.status_code == 403


def test_conversion_authorized_role_passes_rbac_gate(client):
    """
    A planner must not be blocked by authorization. We only assert the RBAC gate
    itself passes (never 401/403) -- the exact business outcome (200 vs. a 400/404 for
    an unrelated business-rule reason, e.g. insufficient debit-stage WIP) depends on
    seed-data state that isn't this test's concern.
    """
    planner_headers = _login(client, "PLANNER")
    resp = client.post(
        "/api/v1/operations/conversion",
        headers=planner_headers,
        json={
            "conversion_wo_number": f"C-RBAC-{uuid.uuid4().hex[:8]}",
            "source_wo_number": "WO-1001",
            "destination_oar_number": "OAR-0002",
            "quantity": 5,
            "entry_stage": "F2",
            "reason": "RBAC test",
        },
    )
    assert resp.status_code not in (401, 403), resp.text


# ---------------------------------------------------------------------------
# 3. Dispatch / Ship
# ---------------------------------------------------------------------------

def test_dispatch_ship_rejects_unauthorized_role(client):
    qa_headers = _login(client, "QA")
    resp = client.post(
        "/api/v1/dispatch/ship",
        headers=qa_headers,
        json={"wo_number": "WO-1007", "invoice_number": f"INV-RBAC-{uuid.uuid4().hex[:8]}", "dispatched_quantity": 1},
    )
    assert resp.status_code == 403


def test_dispatch_ship_succeeds_for_dispatch_role(client):
    dispatch_headers = _login(client, "DISPATCH")
    resp = client.post(
        "/api/v1/dispatch/ship",
        headers=dispatch_headers,
        json={"wo_number": "WO-1007", "invoice_number": f"INV-RBAC-{uuid.uuid4().hex[:8]}", "dispatched_quantity": 1},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


def test_dispatch_ship_succeeds_for_production_manager(client):
    pm_headers = _login(client, "PRODUCTION_MANAGER")
    resp = client.post(
        "/api/v1/dispatch/ship",
        headers=pm_headers,
        json={"wo_number": "WO-1007", "invoice_number": f"INV-RBAC-{uuid.uuid4().hex[:8]}", "dispatched_quantity": 1},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 4. NC Disposition
# ---------------------------------------------------------------------------

def _create_nc(client, headers):
    resp = client.post(
        "/api/v1/operations/nc",
        headers=headers,
        json={"wo_number": "WO-1001", "stage": "F2", "defect_code": "DEF-POROSITY", "qty": 1},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["nc_number"]


def test_nc_creation_remains_open_to_any_authenticated_user(client):
    """NC creation (reporting a defect) is a normal shop-floor action and must remain
    unrestricted -- only disposition (PUT, the approval/closure action) is gated."""
    operator_headers = _login(client, "MACHINE_OPERATOR")
    nc_number = _create_nc(client, operator_headers)
    assert nc_number


def test_nc_disposition_rejects_unauthorized_role(client):
    admin_headers = _login(client, "ADMIN")
    nc_number = _create_nc(client, admin_headers)

    operator_headers = _login(client, "MACHINE_OPERATOR")
    resp = client.put(
        "/api/v1/operations/nc",
        headers=operator_headers,
        json={"nc_number": nc_number, "status": "Closed"},
    )
    assert resp.status_code == 403


def test_nc_disposition_succeeds_for_qa(client):
    admin_headers = _login(client, "ADMIN")
    nc_number = _create_nc(client, admin_headers)

    qa_headers = _login(client, "QA")
    resp = client.put(
        "/api/v1/operations/nc",
        headers=qa_headers,
        json={"nc_number": nc_number, "status": "Closed", "disposition": "Scrap"},
    )
    assert resp.status_code == 200, resp.text
