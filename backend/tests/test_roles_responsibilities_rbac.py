"""RBAC coverage for the explicit OMS Roles & Responsibilities matrix (see
app/core/roles.py for the enforced tuples). Every assertion here hits a real HTTP
endpoint through TestClient -- these prove the backend itself returns 403 for an
unauthorized mutation, not that a frontend button happens to be hidden.

Resource categories covered, per the task's own checklist: Customer, PO, Schedule,
OAR, WO, Production, Movement, Rejection, Conversion, Scrap, Packing/BSR, Dispatch,
Tracking, Reports, User administration.
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
    "STORE": ("store@vspl.com", "store123"),
    "MACHINE_OPERATOR": ("operator@vspl.com", "op123"),
    "DATA_ANALYST": ("analyst@vspl.com", "analyst123"),
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


def _unique(prefix="RBAC"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _setup_customer_and_part(client, admin_headers):
    code = _unique("CUST")
    resp = client.post(
        "/api/v1/masters/customers", headers=admin_headers,
        json={"customer_code": code, "name": f"RBAC Test Co {code}"},
    )
    assert resp.status_code == 200, resp.text
    return code


def _intake_oar(client, admin_headers, customer_code, part_number="BRZ-BUSH-100", po_qty=10):
    resp = client.post(
        "/api/v1/operations/intake", headers=admin_headers,
        json={
            "customer_code": customer_code, "customer_name": f"RBAC Test Co {customer_code}",
            "customer_po": _unique("PO"), "part_number": part_number,
            "po_quantity": po_qty, "max_batch_size": po_qty,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ===========================================================================
# CUSTOMER master
# ===========================================================================

def test_customer_master_create_allowed_for_planner(client):
    headers = _login(client, "PLANNER")
    resp = client.post(
        "/api/v1/masters/customers", headers=headers,
        json={"customer_code": _unique("CUST"), "name": "Planner-Created Co"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", ["PRODUCTION_MANAGER", "STORE", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_customer_master_create_rejected_for_non_planning_roles(client, role):
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/masters/customers", headers=headers,
        json={"customer_code": _unique("CUST"), "name": f"{role} attempted create"},
    )
    assert resp.status_code == 403


# ===========================================================================
# PO master
# ===========================================================================

def test_po_master_create_allowed_for_planner(client):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    headers = _login(client, "PLANNER")
    resp = client.post(
        "/api/v1/masters/pos", headers=headers,
        json={"po_number": _unique("PO"), "customer_code": code, "lines": [{"part_number": "BRZ-BUSH-100", "po_qty": 10}]},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", ["PRODUCTION_MANAGER", "STORE", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_po_master_create_rejected_for_non_planning_roles(client, role):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/masters/pos", headers=headers,
        json={"po_number": _unique("PO"), "customer_code": code, "lines": [{"part_number": "BRZ-BUSH-100", "po_qty": 10}]},
    )
    assert resp.status_code == 403


# ===========================================================================
# SCHEDULE master
# ===========================================================================

def test_schedule_master_create_allowed_for_planner(client):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    headers = _login(client, "PLANNER")
    resp = client.post(
        "/api/v1/masters/schedules", headers=headers,
        json={"customer_code": code, "part_number": "BRZ-BUSH-100", "scheduled_qty": 10},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", ["PRODUCTION_MANAGER", "STORE", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_schedule_master_create_rejected_for_non_planning_roles(client, role):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/masters/schedules", headers=headers,
        json={"customer_code": code, "part_number": "BRZ-BUSH-100", "scheduled_qty": 10},
    )
    assert resp.status_code == 403


# ===========================================================================
# OAR (Order Intake) creation
# ===========================================================================

def test_oar_creation_allowed_for_planner(client):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    headers = _login(client, "PLANNER")
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": code, "customer_name": f"RBAC Test Co {code}",
            "customer_po": _unique("PO"), "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10,
        },
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", ["PRODUCTION_MANAGER", "STORE", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_oar_creation_rejected_for_non_planning_roles(client, role):
    """Production Manager explicitly cannot create/edit an OAR per spec."""
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": code, "customer_name": f"RBAC Test Co {code}",
            "customer_po": _unique("PO"), "part_number": "BRZ-BUSH-100",
            "po_quantity": 10, "max_batch_size": 10,
        },
    )
    assert resp.status_code == 403


# ===========================================================================
# WO release (carve-out: Production Manager keeps this)
# ===========================================================================

def test_wo_release_allowed_for_production_manager_carveout(client):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    # This intake auto-releases WOs already; use a fresh unreleased WO scenario isn't
    # directly exposed, so just prove the RBAC gate passes (not 401/403) using an
    # already-released WO number -- the gate is what's under test, not the business
    # outcome of re-releasing.
    headers = _login(client, "PRODUCTION_MANAGER")
    resp = client.post(
        "/api/v1/operations/wo-release", headers=headers,
        json={"wo_number": intake["wos_created"][0], "physical_wo_qty": 10, "route_stages": ["F1", "F2", "DISPATCH"]},
    )
    assert resp.status_code not in (401, 403), resp.text


@pytest.mark.parametrize("role", ["STORE", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_wo_release_rejected_for_non_planning_roles(client, role):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/operations/wo-release", headers=headers,
        json={"wo_number": intake["wos_created"][0], "physical_wo_qty": 10, "route_stages": ["F1", "F2", "DISPATCH"]},
    )
    assert resp.status_code == 403


# ===========================================================================
# PRODUCTION entry
# ===========================================================================

def test_production_entry_allowed_for_production_manager(client):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    headers = _login(client, "PRODUCTION_MANAGER")
    resp = client.post(
        "/api/v1/production/entry", headers=headers,
        json={"wo_number": intake["wos_created"][0], "stage": "F1", "good_qty": 1, "rejected_quantity": 0},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", ["PLANNER", "STORE", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_production_entry_rejected_for_non_production_roles(client, role):
    """Planner explicitly cannot do production entry per spec -- a new restriction
    (previously Planner was included in PRODUCTION_ENTRY_ROLES)."""
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/production/entry", headers=headers,
        json={"wo_number": intake["wos_created"][0], "stage": "F1", "good_qty": 1, "rejected_quantity": 0},
    )
    assert resp.status_code == 403


# ===========================================================================
# MOVEMENT (material movement between stages)
# ===========================================================================

def test_movement_allowed_for_store(client):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    wo_number = intake["wos_created"][0]
    client.post(
        "/api/v1/production/entry", headers=admin_headers,
        json={"wo_number": wo_number, "stage": "F1", "good_qty": 5, "rejected_quantity": 0},
    )
    headers = _login(client, "STORE")
    resp = client.post(
        "/api/v1/production/move", headers=headers,
        json={"wo_number": wo_number, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 1},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", ["PLANNER", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_movement_rejected_for_non_movement_roles(client, role):
    """Planner explicitly cannot do 'arbitrary material movement' per spec -- a new
    restriction (movement was previously open to any authenticated user)."""
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    wo_number = intake["wos_created"][0]
    client.post(
        "/api/v1/production/entry", headers=admin_headers,
        json={"wo_number": wo_number, "stage": "F1", "good_qty": 5, "rejected_quantity": 0},
    )
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/production/move", headers=headers,
        json={"wo_number": wo_number, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 1},
    )
    assert resp.status_code == 403


# ===========================================================================
# REJECTION (NC raising stays open; disposition approval is gated)
# ===========================================================================

def _build_ready_for_dispatch_wo(client, admin_headers, code):
    """Build a WO through a minimal FI->DISPATCH route, produce it, pack it, so it's
    genuinely ready for dispatch -- rather than relying on shared baseline WO-1007,
    whose ready-for-dispatch quantity has been exhausted by other tests/imports run
    against this same dev database over the course of this session."""
    intake = _intake_oar(client, admin_headers, code, po_qty=5)
    wo_number = intake["wos_created"][0]
    release = client.post(
        "/api/v1/operations/wo-release", headers=admin_headers,
        json={"wo_number": wo_number, "physical_wo_qty": 5, "route_stages": ["FI", "DISPATCH"]},
    )
    assert release.status_code == 200, release.text
    entry = client.post(
        "/api/v1/production/entry", headers=admin_headers,
        json={"wo_number": wo_number, "stage": "FI", "good_qty": 5, "rejected_quantity": 0},
    )
    assert entry.status_code == 200, entry.text
    pack = client.post(
        "/api/v1/packing/update", headers=admin_headers,
        json={"wo_number": wo_number, "packed_quantity": 5},
    )
    assert pack.status_code == 200, pack.text
    return wo_number


def _create_nc(client, headers, wo_number):
    resp = client.post(
        "/api/v1/operations/nc", headers=headers,
        json={"wo_number": wo_number, "stage": "F1", "defect_code": "DIM", "qty": 1},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["nc_number"]


def test_nc_raising_stays_open_to_any_authenticated_role(client):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    dispatch_headers = _login(client, "DISPATCH")
    nc_number = _create_nc(client, dispatch_headers, intake["wos_created"][0])
    assert nc_number


@pytest.mark.parametrize("role", ["STORE", "DISPATCH", "PLANNER"])
def test_nc_disposition_rejected_for_non_qa_roles(client, role):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    nc_number = _create_nc(client, admin_headers, intake["wos_created"][0])
    headers = _login(client, role)
    resp = client.put(
        "/api/v1/operations/nc", headers=headers,
        json={"nc_number": nc_number, "status": "Closed"},
    )
    assert resp.status_code == 403


# ===========================================================================
# CONVERSION (planner-driven Conversion Module, unrestricted by this spec pass)
# ===========================================================================

def test_conversion_module_passes_rbac_gate_for_planner_and_production_manager(client):
    for role in ("PLANNER", "PRODUCTION_MANAGER"):
        headers = _login(client, role)
        resp = client.post(
            "/api/v1/operations/conversion", headers=headers,
            json={
                "conversion_wo_number": _unique("CWO"), "source_wo_number": "WO-1001",
                "destination_oar_number": "OAR-0002", "quantity": 1, "entry_stage": "F2",
                "reason": "RBAC coverage",
            },
        )
        assert resp.status_code not in (401, 403), f"{role}: {resp.text}"


@pytest.mark.parametrize("role", ["STORE", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_conversion_module_rejected_for_non_conversion_roles(client, role):
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/operations/conversion", headers=headers,
        json={
            "conversion_wo_number": _unique("CWO"), "source_wo_number": "WO-1001",
            "destination_oar_number": "OAR-0002", "quantity": 1, "entry_stage": "F2",
            "reason": "RBAC coverage",
        },
    )
    assert resp.status_code == 403


# ===========================================================================
# SCRAP disposition (QUALITY_APPROVAL_ROLES)
# ===========================================================================

@pytest.mark.parametrize("role", ["STORE", "DISPATCH", "PLANNER", "PRODUCTION_MANAGER", "CEO"])
def test_scrap_disposition_rejected_for_non_qa_roles(client, role):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    nc_number = _create_nc(client, admin_headers, intake["wos_created"][0])
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/rejection/disposition", headers=headers,
        json={"nc_number": nc_number, "action": "SCRAP", "quantity": 1, "reason": "RBAC coverage"},
    )
    assert resp.status_code == 403


def test_scrap_disposition_allowed_for_qa(client):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    intake = _intake_oar(client, admin_headers, code)
    nc_number = _create_nc(client, admin_headers, intake["wos_created"][0])
    headers = _login(client, "QA")
    resp = client.post(
        "/api/v1/rejection/disposition", headers=headers,
        json={"nc_number": nc_number, "action": "SCRAP", "quantity": 1, "reason": "RBAC coverage"},
    )
    assert resp.status_code == 200, resp.text


# ===========================================================================
# PACKING / BSR
# ===========================================================================

@pytest.mark.parametrize("role", ["PLANNER", "STORE", "QA", "PRODUCTION_MANAGER", "CEO", "DATA_ANALYST"])
def test_packing_update_rejected_for_non_packing_roles(client, role):
    """Packing/BSR update was previously open to ANY authenticated user; this is a
    new restriction per spec ("Packing/BSR" is Dispatch's remit)."""
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/packing/update", headers=headers,
        json={"wo_number": "WO-1006", "packed_quantity": 1},
    )
    assert resp.status_code == 403


def test_packing_update_passes_rbac_gate_for_dispatch(client):
    headers = _login(client, "DISPATCH")
    resp = client.post(
        "/api/v1/packing/update", headers=headers,
        json={"wo_number": "WO-1006", "packed_quantity": 1},
    )
    assert resp.status_code not in (401, 403), resp.text


# ===========================================================================
# DISPATCH execution
# ===========================================================================

@pytest.mark.parametrize("role", ["PLANNER", "STORE", "QA", "PRODUCTION_MANAGER", "CEO", "DATA_ANALYST"])
def test_dispatch_execution_rejected_for_non_dispatch_roles(client, role):
    headers = _login(client, role)
    resp = client.post(
        "/api/v1/dispatch/ship", headers=headers,
        json={"wo_number": "WO-1007", "invoice_number": _unique("INV"), "dispatched_quantity": 1},
    )
    assert resp.status_code == 403


def test_dispatch_execution_allowed_for_dispatch_role(client):
    admin_headers = _login(client, "ADMIN")
    code = _setup_customer_and_part(client, admin_headers)
    wo_number = _build_ready_for_dispatch_wo(client, admin_headers, code)
    headers = _login(client, "DISPATCH")
    resp = client.post(
        "/api/v1/dispatch/ship", headers=headers,
        json={"wo_number": wo_number, "invoice_number": _unique("INV"), "dispatched_quantity": 5},
    )
    assert resp.status_code == 200, resp.text


# ===========================================================================
# TRACKING (broad read access for every role, including CEO and Data Analyst)
#
# The dedicated Tracking & Search module (/api/v1/tracking/...) is a separate,
# not-yet-committed feature -- this checks the same "read is open to every
# authenticated role" property against the pre-existing WO list/tracking endpoint
# instead, so this test suite is self-contained and passes on its own commit.
# ===========================================================================

@pytest.mark.parametrize("role", ["ADMIN", "PLANNER", "PRODUCTION_MANAGER", "STORE", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_tracking_read_access_open_to_every_role(client, role):
    headers = _login(client, role)
    resp = client.get("/api/v1/work-orders", headers=headers, params={"search": "BRZ"})
    assert resp.status_code == 200, resp.text


# ===========================================================================
# REPORTS / ANALYTICS / DASHBOARD (broad read access)
# ===========================================================================

@pytest.mark.parametrize("role", ["CEO", "DATA_ANALYST", "STORE", "QA"])
def test_dashboard_and_analytics_read_access_open_to_every_role(client, role):
    headers = _login(client, role)
    resp = client.get("/api/v1/dashboard/stats", headers=headers)
    assert resp.status_code == 200, resp.text
    resp2 = client.get("/api/v1/analytics/kpis/plant", headers=headers)
    assert resp2.status_code == 200, resp2.text


# ===========================================================================
# USER ADMINISTRATION (Super Admin only)
# ===========================================================================

@pytest.mark.parametrize("role", ["PLANNER", "PRODUCTION_MANAGER", "STORE", "QA", "DISPATCH", "CEO", "DATA_ANALYST"])
def test_user_administration_rejected_for_non_admin_roles(client, role):
    headers = _login(client, role)
    list_resp = client.get("/api/v1/users", headers=headers)
    assert list_resp.status_code == 403

    create_resp = client.post(
        "/api/v1/users", headers=headers,
        json={"full_name": "Escalation Attempt", "email": f"{_unique('esc').lower()}@vspl.com", "role": "admin"},
    )
    assert create_resp.status_code == 403


def test_user_administration_allowed_for_admin(client):
    headers = _login(client, "ADMIN")
    resp = client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 200, resp.text


# ===========================================================================
# DATA_ANALYST cannot mutate manufacturing transactions or master data
# ===========================================================================

@pytest.mark.parametrize("endpoint,payload", [
    ("/api/v1/masters/customers", {"customer_code": "X", "name": "X"}),
    ("/api/v1/production/move", {"wo_number": "WO-1001", "from_stage": "F1", "to_stage": "F2", "quantity_moved": 1}),
    ("/api/v1/production/entry", {"wo_number": "WO-1001", "stage": "F1", "good_qty": 1, "rejected_quantity": 0}),
    ("/api/v1/dispatch/ship", {"wo_number": "WO-1007", "invoice_number": "X", "dispatched_quantity": 1}),
    ("/api/v1/packing/update", {"wo_number": "WO-1006", "packed_quantity": 1}),
])
def test_data_analyst_cannot_mutate_anything(client, endpoint, payload):
    headers = _login(client, "DATA_ANALYST")
    resp = client.post(endpoint, headers=headers, json=payload)
    assert resp.status_code == 403, f"{endpoint}: {resp.text}"
