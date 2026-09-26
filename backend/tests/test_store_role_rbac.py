"""RBAC regression tests for the STORE role (physical material handling).

STORE must be able to:
  - Move parts on the shop floor (existing Move Parts workflow, unchanged validation)
  - Record a melting entry against an already-decided SCRAP disposition

STORE must NOT be able to:
  - Approve/create any disposition (CONVERT_PART / SAME_PART / CWO / SCRAP / DEVIATION_ACCEPT)
  - Enter production completion
  - Release/create a WO, or anything else gated to PLANNING_ROLES / QUALITY_OVERSIGHT_ROLES
    / DISPATCH_ROLES / ADMIN

Every test drives the real HTTP boundary (TestClient -> routing -> auth -> RBAC ->
service -> DB -> response), matching the existing convention in
tests/test_rbac_remediation.py and tests/test_red_team.py.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app

SEEDED_LOGINS = {
    "ADMIN": ("admin@vspl.com", "admin123"),
    "PLANNER": ("planner@vspl.com", "planner123"),
    "QA": ("qa@vspl.com", "qa123"),
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


def _login(client, role_key):
    email, password = SEEDED_LOGINS[role_key]
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _intake_wo(client, token, po_qty=100):
    resp = client.post(
        "/api/v1/operations/intake",
        headers=_auth(token),
        json={
            "customer_code": "CUST-STORETEST",
            "customer_name": "Store Test Customer",
            "customer_po": f"PO-STORE-{uuid.uuid4().hex[:8]}",
            "part_number": f"PART-STORE-{uuid.uuid4().hex[:6]}",
            "po_quantity": po_qty,
            "max_batch_size": po_qty,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["wos_created"][0]


def _produce(client, admin_token, wo, good_qty, rejected=0):
    payload = {"wo_number": wo, "stage": "F1", "good_qty": good_qty, "rejected_quantity": rejected}
    if rejected > 0:
        payload["defect_code"] = "DEF-POROSITY"
    resp = client.post(
        "/api/v1/production/entry", headers=_auth(admin_token),
        json=payload
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1-2. STORE can access Move Parts and create a valid movement
# ---------------------------------------------------------------------------

def test_store_can_access_move_parts_endpoint(client):
    admin = _login(client, "ADMIN")
    store = _login(client, "STORE")
    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=30)

    resp = client.post(
        "/api/v1/production/move", headers=_auth(store),
        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 30, "rejected_quantity": 0}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# 3. STORE cannot move more than available WIP
# ---------------------------------------------------------------------------

def test_store_cannot_move_more_than_available_wip(client):
    admin = _login(client, "ADMIN")
    store = _login(client, "STORE")
    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=20)

    resp = client.post(
        "/api/v1/production/move", headers=_auth(store),
        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 999, "rejected_quantity": 0}
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# 4. STORE cannot cross-WO move
# ---------------------------------------------------------------------------

def test_store_cannot_cross_wo_move(client):
    admin = _login(client, "ADMIN")
    store = _login(client, "STORE")
    wo_a = _intake_wo(client, admin, po_qty=50)
    wo_b = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo_a, good_qty=20)

    resp = client.post(
        "/api/v1/production/move", headers=_auth(store),
        json={
            "wo_number": wo_a, "target_wo_number": wo_b,
            "from_stage": "F1", "to_stage": "F2", "quantity_moved": 10, "rejected_quantity": 0
        }
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# 5. STORE cannot skip stages
# ---------------------------------------------------------------------------

def test_store_cannot_skip_stages(client):
    admin = _login(client, "ADMIN")
    store = _login(client, "STORE")
    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=20)

    resp = client.post(
        "/api/v1/production/move", headers=_auth(store),
        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F3", "quantity_moved": 10, "rejected_quantity": 0}
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# 6. STORE can record conversion material sent for melting
# ---------------------------------------------------------------------------

def test_store_can_record_melting_entry(client):
    admin = _login(client, "ADMIN")
    qa = _login(client, "QA")
    store = _login(client, "STORE")

    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=0, rejected=20)

    # find the auto-created rejection tracking record for this WO
    listing = client.get("/api/v1/rejection", headers=_auth(admin), params={"wo_number": wo})
    assert listing.status_code == 200, listing.text
    nc_number = listing.json()[0]["nc_number"]

    scrap_resp = client.post(
        "/api/v1/rejection/disposition", headers=_auth(qa),
        json={"nc_number": nc_number, "action": "SCRAP", "quantity": 20, "reason": "unrecoverable"}
    )
    assert scrap_resp.status_code == 200, scrap_resp.text

    detail = client.get(f"/api/v1/rejection/{nc_number}", headers=_auth(admin))
    disposition_id = detail.json()["disposition_history"][0]["id"]

    melt_resp = client.post(
        "/api/v1/rejection/melting-entry", headers=_auth(store),
        json={"disposition_id": disposition_id, "melting_destination": "Furnace Bay 1"}
    )
    assert melt_resp.status_code == 200, melt_resp.text
    assert melt_resp.json()["melting_status"] == "SENT_FOR_MELTING"
    assert melt_resp.json()["sent_by"] == "Krishna Murthy (Store)"


def test_store_cannot_record_melting_entry_for_non_scrap_disposition(client):
    """Melting entry only applies to a SCRAP disposition. A DEVIATION_ACCEPT (or any
    other non-SCRAP) disposition must be rejected, not silently treated as scrap
    material."""
    admin = _login(client, "ADMIN")
    qa = _login(client, "QA")
    store = _login(client, "STORE")

    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=0, rejected=20)

    listing = client.get("/api/v1/rejection", headers=_auth(admin), params={"wo_number": wo})
    nc_number = listing.json()[0]["nc_number"]

    deviation_resp = client.post(
        "/api/v1/rejection/disposition", headers=_auth(qa),
        json={"nc_number": nc_number, "action": "DEVIATION_ACCEPT", "quantity": 20, "reason": "accepted under concession"}
    )
    assert deviation_resp.status_code == 200, deviation_resp.text

    detail = client.get(f"/api/v1/rejection/{nc_number}", headers=_auth(admin))
    disposition_id = detail.json()["disposition_history"][0]["id"]

    melt_resp = client.post(
        "/api/v1/rejection/melting-entry", headers=_auth(store),
        json={"disposition_id": disposition_id}
    )
    assert melt_resp.status_code == 400, melt_resp.text


def test_store_cannot_record_melting_entry_twice_for_same_disposition(client):
    """Once a SCRAP disposition has already been sent for melting, a second melting
    entry against the same disposition_id must be rejected -- material cannot be
    consumed twice."""
    admin = _login(client, "ADMIN")
    qa = _login(client, "QA")
    store = _login(client, "STORE")

    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=0, rejected=20)

    listing = client.get("/api/v1/rejection", headers=_auth(admin), params={"wo_number": wo})
    nc_number = listing.json()[0]["nc_number"]

    scrap_resp = client.post(
        "/api/v1/rejection/disposition", headers=_auth(qa),
        json={"nc_number": nc_number, "action": "SCRAP", "quantity": 20, "reason": "unrecoverable"}
    )
    assert scrap_resp.status_code == 200, scrap_resp.text

    detail = client.get(f"/api/v1/rejection/{nc_number}", headers=_auth(admin))
    disposition_id = detail.json()["disposition_history"][0]["id"]

    first = client.post(
        "/api/v1/rejection/melting-entry", headers=_auth(store),
        json={"disposition_id": disposition_id}
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/v1/rejection/melting-entry", headers=_auth(store),
        json={"disposition_id": disposition_id}
    )
    assert second.status_code == 400, second.text


# ---------------------------------------------------------------------------
# 7-9. STORE cannot approve conversion / DEVIATION_ACCEPT / scrap
# ---------------------------------------------------------------------------

def test_store_cannot_approve_conversion(client):
    admin = _login(client, "ADMIN")
    store = _login(client, "STORE")
    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=0, rejected=20)

    listing = client.get("/api/v1/rejection", headers=_auth(admin), params={"wo_number": wo})
    nc_number = listing.json()[0]["nc_number"]

    resp = client.post(
        "/api/v1/rejection/disposition", headers=_auth(store),
        json={
            "nc_number": nc_number, "action": "CONVERT_PART", "quantity": 5,
            "destination_oar_number": "OAR-0001", "entry_stage": "F1",
            "conversion_wo_number": f"CWO-STORE-{uuid.uuid4().hex[:8]}", "reason": "store should not be able to do this"
        }
    )
    assert resp.status_code == 403, resp.text


def test_store_cannot_perform_deviation_accept(client):
    admin = _login(client, "ADMIN")
    store = _login(client, "STORE")
    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=0, rejected=20)

    listing = client.get("/api/v1/rejection", headers=_auth(admin), params={"wo_number": wo})
    nc_number = listing.json()[0]["nc_number"]

    resp = client.post(
        "/api/v1/rejection/disposition", headers=_auth(store),
        json={"nc_number": nc_number, "action": "DEVIATION_ACCEPT", "quantity": 5, "reason": "store cannot decide this"}
    )
    assert resp.status_code == 403, resp.text


def test_store_cannot_approve_scrap(client):
    admin = _login(client, "ADMIN")
    store = _login(client, "STORE")
    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=0, rejected=20)

    listing = client.get("/api/v1/rejection", headers=_auth(admin), params={"wo_number": wo})
    nc_number = listing.json()[0]["nc_number"]

    resp = client.post(
        "/api/v1/rejection/disposition", headers=_auth(store),
        json={"nc_number": nc_number, "action": "SCRAP", "quantity": 5, "reason": "store cannot decide this"}
    )
    assert resp.status_code == 403, resp.text


def test_store_cannot_record_melting_entry_without_existing_scrap_decision(client):
    """STORE cannot skip the decision step -- there must already be a SCRAP
    disposition; a made-up disposition id is rejected, not silently accepted."""
    store = _login(client, "STORE")
    resp = client.post(
        "/api/v1/rejection/melting-entry", headers=_auth(store),
        json={"disposition_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 10. STORE cannot create/release WO
# ---------------------------------------------------------------------------

def test_store_cannot_release_wo(client):
    admin = _login(client, "ADMIN")
    store = _login(client, "STORE")
    wo = _intake_wo(client, admin, po_qty=25)

    resp = client.post(
        "/api/v1/operations/wo-release", headers=_auth(store),
        json={"wo_number": wo, "physical_wo_qty": 25, "route_stages": ["F1", "F2", "DISPATCH"]}
    )
    assert resp.status_code == 403, resp.text


def test_store_cannot_create_order_intake(client):
    store = _login(client, "STORE")
    resp = client.post(
        "/api/v1/operations/intake", headers=_auth(store),
        json={
            "customer_code": "CUST-STOREINTAKE", "customer_name": "Store Intake Attempt",
            "customer_po": f"PO-{uuid.uuid4().hex[:8]}", "part_number": f"PART-{uuid.uuid4().hex[:6]}",
            "po_quantity": 10, "max_batch_size": 10
        }
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 11. STORE cannot enter production completion
# ---------------------------------------------------------------------------

def test_store_cannot_enter_production_completion(client):
    admin = _login(client, "ADMIN")
    store = _login(client, "STORE")
    wo = _intake_wo(client, admin, po_qty=50)

    resp = client.post(
        "/api/v1/production/entry", headers=_auth(store),
        json={"wo_number": wo, "stage": "F1", "good_qty": 10, "rejected_quantity": 0}
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 12. STORE cannot dispatch
# ---------------------------------------------------------------------------

def test_store_cannot_dispatch(client):
    store = _login(client, "STORE")
    resp = client.post(
        "/api/v1/dispatch/ship", headers=_auth(store),
        json={"wo_number": "WO-1001", "dispatched_quantity": 1, "invoice_number": "INV-STORE-TEST"}
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 13. STORE cannot manage users
# ---------------------------------------------------------------------------

def test_store_cannot_register_users(client):
    store = _login(client, "STORE")
    resp = client.post(
        "/api/v1/auth/register", headers=_auth(store),
        json={
            "full_name": "Fake Admin", "email": f"fake-{uuid.uuid4().hex[:8]}@vspl.com",
            "password": "whatever123", "role": "admin"
        }
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 14. STORE cannot modify masters (conversion part mapping is the only writable master)
# ---------------------------------------------------------------------------

def test_store_cannot_create_conversion_mapping(client):
    store = _login(client, "STORE")
    resp = client.post(
        "/api/v1/conversion-mapping", headers=_auth(store),
        json={"source_part_number": "PART-X", "destination_part_number": "PART-Y", "conversion_type": "PART_TO_PART"}
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 15. STORE actions create correct audit records
# ---------------------------------------------------------------------------

def test_store_melting_entry_creates_audit_record_with_authenticated_identity(client):
    admin = _login(client, "ADMIN")
    qa = _login(client, "QA")
    store = _login(client, "STORE")

    wo = _intake_wo(client, admin, po_qty=50)
    _produce(client, admin, wo, good_qty=0, rejected=15)

    listing = client.get("/api/v1/rejection", headers=_auth(admin), params={"wo_number": wo})
    nc_number = listing.json()[0]["nc_number"]
    client.post(
        "/api/v1/rejection/disposition", headers=_auth(qa),
        json={"nc_number": nc_number, "action": "SCRAP", "quantity": 15, "reason": "audit test"}
    )
    detail = client.get(f"/api/v1/rejection/{nc_number}", headers=_auth(admin))
    disposition_id = detail.json()["disposition_history"][0]["id"]

    # Client attempts to smuggle a fake operator identity via remarks/body -- the
    # audit trail must reflect the AUTHENTICATED store user, never a client-supplied name.
    resp = client.post(
        "/api/v1/rejection/melting-entry", headers=_auth(store),
        json={"disposition_id": disposition_id, "remarks": "Sent by 'Totally Not Store' (fake)"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent_by"] == "Krishna Murthy (Store)"

    audit_logs = client.get("/api/v1/admin/audit-logs", headers=_auth(admin))
    assert audit_logs.status_code == 200
    matching = [a for a in audit_logs.json() if a.get("entity_id") == disposition_id]
    assert len(matching) == 1
    assert matching[0]["user_name"] == "Krishna Murthy (Store)"
    assert matching[0]["action"] == "REJECTION_MELTING_ENTRY"


# ---------------------------------------------------------------------------
# 16. Unauthorized endpoint calls return 403 (aggregate spot-check)
# ---------------------------------------------------------------------------

def test_store_unauthorized_calls_return_403_not_500_or_200(client):
    store = _login(client, "STORE")

    checks = [
        ("POST", "/api/v1/operations/wo-release", {"wo_number": "WO-1001", "physical_wo_qty": 10, "route_stages": ["F1", "DISPATCH"]}),
        ("POST", "/api/v1/operations/conversion", {"conversion_wo_number": f"C-{uuid.uuid4().hex[:8]}", "source_wo_number": "WO-1001", "destination_oar_number": "OAR-0001", "quantity": 1, "entry_stage": "F1", "reason": "x"}),
        ("PUT", "/api/v1/operations/nc", {"nc_number": "NC-00001", "status": "Closed"}),
        ("POST", "/api/v1/dispatch/ship", {"wo_number": "WO-1001", "dispatched_quantity": 1, "invoice_number": "INV-X"}),
    ]
    for method, url, body in checks:
        resp = client.request(method, url, headers=_auth(store), json=body)
        assert resp.status_code == 403, f"{method} {url} -> expected 403, got {resp.status_code}: {resp.text}"
