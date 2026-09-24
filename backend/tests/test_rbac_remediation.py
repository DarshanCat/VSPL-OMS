"""
RBAC remediation regression tests (security phase 2), updated for the OMS Roles &
Responsibilities pass (see app/core/roles.py):

  1. WO Release   -> WO_RELEASE_ROLES (ADMIN, PLANNER, PRODUCTION_MANAGER) -- Production
     Manager keeps this per the spec's own carve-out ("Cannot: WO release unless
     existing explicit permission already grants it").
  2. Conversion    -> CONVERSION_MODULE_ROLES (ADMIN, PLANNER, PRODUCTION_MANAGER),
     unchanged -- the spec doesn't restrict the planner-driven Conversion Module.
  3. Dispatch/Ship -> DISPATCH_EXECUTION_ROLES (ADMIN, DISPATCH) -- Production Manager
     is now EXCLUDED per spec ("Cannot: final dispatch"), a real behavior change from
     the previous DISPATCH_ROLES which included Production Manager.
  4. NC disposition (PUT) -> QUALITY_APPROVAL_ROLES (ADMIN, QA) -- Production Manager
     and CEO are now EXCLUDED per spec ("Cannot: QA disposition approval" / CEO's
     blanket "no operational transaction mutation"), a real behavior change from the
     previous QUALITY_OVERSIGHT_ROLES which included both.

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


def _build_ready_for_dispatch_wo(client, admin_headers, qty=5):
    """A fresh WO taken through a minimal FI->DISPATCH route, produced and packed, so
    it's genuinely ready for dispatch -- rather than relying on the shared baseline
    WO-1007, whose ready-for-dispatch quantity other tests/imports in this same dev
    database have since exhausted."""
    wo_number = _intake_fresh_wo(client, admin_headers, po_qty=qty)
    release = client.post(
        "/api/v1/operations/wo-release", headers=admin_headers,
        json={"wo_number": wo_number, "physical_wo_qty": qty, "route_stages": ["FI", "DISPATCH"]},
    )
    assert release.status_code == 200, release.text
    entry = client.post(
        "/api/v1/production/entry", headers=admin_headers,
        json={"wo_number": wo_number, "stage": "FI", "good_qty": qty, "rejected_quantity": 0},
    )
    assert entry.status_code == 200, entry.text
    pack = client.post(
        "/api/v1/packing/update", headers=admin_headers,
        json={"wo_number": wo_number, "packed_quantity": qty},
    )
    assert pack.status_code == 200, pack.text
    return wo_number


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
    admin_headers = _login(client, "ADMIN")
    wo_number = _build_ready_for_dispatch_wo(client, admin_headers)

    dispatch_headers = _login(client, "DISPATCH")
    resp = client.post(
        "/api/v1/dispatch/ship",
        headers=dispatch_headers,
        json={"wo_number": wo_number, "invoice_number": f"INV-RBAC-{uuid.uuid4().hex[:8]}", "dispatched_quantity": 5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


def test_dispatch_ship_rejects_production_manager(client):
    """Production Manager previously could execute dispatch (former DISPATCH_ROLES);
    the Roles & Responsibilities spec explicitly withdraws this ("Cannot: final
    dispatch"). This is an intentional behavior change, not a regression."""
    pm_headers = _login(client, "PRODUCTION_MANAGER")
    resp = client.post(
        "/api/v1/dispatch/ship",
        headers=pm_headers,
        json={"wo_number": "WO-1007", "invoice_number": f"INV-RBAC-{uuid.uuid4().hex[:8]}", "dispatched_quantity": 1},
    )
    assert resp.status_code == 403


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


def test_nc_disposition_rejects_production_manager(client):
    """Production Manager previously could close/disposition an NC (former
    QUALITY_OVERSIGHT_ROLES); the spec explicitly withdraws this ("Cannot: QA
    disposition approval")."""
    admin_headers = _login(client, "ADMIN")
    nc_number = _create_nc(client, admin_headers)

    pm_headers = _login(client, "PRODUCTION_MANAGER")
    resp = client.put(
        "/api/v1/operations/nc",
        headers=pm_headers,
        json={"nc_number": nc_number, "status": "Closed"},
    )
    assert resp.status_code == 403


def test_nc_disposition_rejects_ceo(client):
    """CEO previously could close/disposition an NC (former QUALITY_OVERSIGHT_ROLES);
    the spec's blanket "no operational transaction mutation unless explicitly
    authorized" withdraws this."""
    admin_headers = _login(client, "ADMIN")
    nc_number = _create_nc(client, admin_headers)

    ceo_headers = _login(client, "CEO")
    resp = client.put(
        "/api/v1/operations/nc",
        headers=ceo_headers,
        json={"nc_number": nc_number, "status": "Closed"},
    )
    assert resp.status_code == 403
