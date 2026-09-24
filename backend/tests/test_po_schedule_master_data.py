"""Regression tests for OMS Master Data and PO/Schedule Order Intake.

Covers: Customer Master, PO Master, Schedule Master, schedule-based OAR intake,
PO-to-schedule matching (exact + both mismatch directions), duplicate prevention,
available-PO-quantity enforcement, multiple schedules/PO lines, audit history, and
a proof that the pre-existing plain OAR -> WO workflow is completely unaffected.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
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


def _create_customer(client, headers, code=None):
    code = code or _unique_code()
    resp = client.post(
        "/api/v1/masters/customers", headers=headers,
        json={"customer_code": code, "name": f"Test Customer {code}", "email": "buyer@example.com"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_schedule(client, headers, customer_code, part_number="BRZ-BUSH-100", qty=500, ref=None):
    resp = client.post(
        "/api/v1/masters/schedules", headers=headers,
        json={
            "customer_code": customer_code, "part_number": part_number,
            "scheduled_qty": qty, "customer_schedule_ref": ref or f"CUST-SCH-{uuid.uuid4().hex[:6]}",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_po(client, headers, customer_code, lines):
    resp = client.post(
        "/api/v1/masters/pos", headers=headers,
        json={"po_number": f"PO-{uuid.uuid4().hex[:8].upper()}", "customer_code": customer_code, "lines": lines},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _intake_schedule_oar(client, headers, customer_code, customer_name, schedule):
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": customer_code, "customer_name": customer_name,
            "customer_po": f"AWAITING-PO-{schedule['schedule_number']}",
            "part_number": schedule["part_number"], "po_quantity": schedule["scheduled_qty"],
            "max_batch_size": schedule["scheduled_qty"],
            "source_type": "schedule", "schedule_id": schedule["id"],
        },
    )
    return resp


# ---------------------------------------------------------------------------
# 1. Create customer
# ---------------------------------------------------------------------------

def test_create_customer(client):
    headers = _auth(_login(client))
    code = _unique_code()
    resp = client.post(
        "/api/v1/masters/customers", headers=headers,
        json={"customer_code": code, "name": "Acme Valves", "gst": "29ABCDE1234F1Z5", "email": "ops@acme.test"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["customer_code"] == code
    assert body["is_active"] is True
    assert body["gst"] == "29ABCDE1234F1Z5"


# ---------------------------------------------------------------------------
# 2-4. Schedule without PO -> schedule-based OAR -> awaiting PO
# ---------------------------------------------------------------------------

def test_create_schedule_without_po(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    schedule = _create_schedule(client, headers, customer["customer_code"], qty=500)
    assert schedule["po_status"] == "scheduled"
    assert schedule["linked_oar_number"] is None


def test_schedule_based_oar_shows_awaiting_po(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    schedule = _create_schedule(client, headers, customer["customer_code"], qty=500)

    resp = _intake_schedule_oar(client, headers, customer["customer_code"], customer["name"], schedule)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_type"] == "schedule"
    assert body["oar_po_status"] == "awaiting_po"
    assert "Schedule-based demand" in body["message"]

    schedules = client.get("/api/v1/masters/schedules", headers=headers, params={"customer_code": customer["customer_code"]}).json()
    match = next(s for s in schedules if s["id"] == schedule["id"])
    assert match["po_status"] == "awaiting_po"
    assert match["linked_oar_number"] == body["oar_number"]


# ---------------------------------------------------------------------------
# 5-7. PO created later, matched to the existing schedule OAR, no duplicate
# ---------------------------------------------------------------------------

def test_match_po_to_existing_schedule_oar_creates_no_duplicate(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    schedule = _create_schedule(client, headers, customer["customer_code"], qty=500)
    intake = _intake_schedule_oar(client, headers, customer["customer_code"], customer["name"], schedule)
    oar_number = intake.json()["oar_number"]

    # Duplicate-prevention check surfaces the existing schedule-based OAR.
    dup = client.get(
        "/api/v1/po-matching/check-duplicate", headers=headers,
        params={"customer_code": customer["customer_code"], "part_number": schedule["part_number"]},
    )
    assert dup.status_code == 200, dup.text
    assert dup.json()["has_candidate"] is True
    assert any(c["schedule_id"] == schedule["id"] for c in dup.json()["candidates"])

    po = _create_po(client, headers, customer["customer_code"], [{"part_number": schedule["part_number"], "po_qty": 500}])
    po_line_id = po["lines"][0]["id"]

    candidates = client.get("/api/v1/po-matching/candidates", headers=headers, params={"po_line_id": po_line_id}).json()
    assert any(c["schedule_id"] == schedule["id"] and c["quantity_match"] == "EXACT" for c in candidates)

    match = client.post(
        "/api/v1/po-matching/match", headers=headers,
        json={"po_line_id": po_line_id, "schedule_id": schedule["id"]},
    )
    assert match.status_code == 200, match.text
    assert match.json()["oar_number"] == oar_number  # same OAR, not a new one
    assert match.json()["quantity_match"] == "EXACT"

    # Exactly one OAR exists for this schedule -- never a second one.
    oar_list = client.get("/api/v1/operations/oars", headers=headers, params={"search": oar_number}).json()
    assert sum(1 for o in oar_list if o["oar_number"] == oar_number) == 1


# ---------------------------------------------------------------------------
# 8-10. Quantity match / mismatch messaging
# ---------------------------------------------------------------------------

def test_exact_quantity_match(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    schedule = _create_schedule(client, headers, customer["customer_code"], qty=500)
    _intake_schedule_oar(client, headers, customer["customer_code"], customer["name"], schedule)
    po = _create_po(client, headers, customer["customer_code"], [{"part_number": schedule["part_number"], "po_qty": 500}])

    candidates = client.get("/api/v1/po-matching/candidates", headers=headers, params={"po_line_id": po["lines"][0]["id"]}).json()
    match = next(c for c in candidates if c["schedule_id"] == schedule["id"])
    assert match["quantity_match"] == "EXACT"
    assert match["mismatch_message"] is None


def test_po_below_schedule_mismatch_message(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    schedule = _create_schedule(client, headers, customer["customer_code"], qty=500)
    _intake_schedule_oar(client, headers, customer["customer_code"], customer["name"], schedule)
    po = _create_po(client, headers, customer["customer_code"], [{"part_number": schedule["part_number"], "po_qty": 400}])

    candidates = client.get("/api/v1/po-matching/candidates", headers=headers, params={"po_line_id": po["lines"][0]["id"]}).json()
    match = next(c for c in candidates if c["schedule_id"] == schedule["id"])
    assert match["quantity_match"] == "PO_BELOW_SCHEDULE"
    assert match["mismatch_message"] == "Quantity mismatch: PO is 100 below schedule"

    # Refusing to acknowledge the mismatch blocks the match.
    blocked = client.post(
        "/api/v1/po-matching/match", headers=headers,
        json={"po_line_id": po["lines"][0]["id"], "schedule_id": schedule["id"]},
    )
    assert blocked.status_code == 409, blocked.text

    confirmed = client.post(
        "/api/v1/po-matching/match", headers=headers,
        json={"po_line_id": po["lines"][0]["id"], "schedule_id": schedule["id"], "acknowledge_mismatch": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["quantity_match"] == "PO_BELOW_SCHEDULE"


def test_po_above_schedule_mismatch_message(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    schedule = _create_schedule(client, headers, customer["customer_code"], qty=500)
    _intake_schedule_oar(client, headers, customer["customer_code"], customer["name"], schedule)
    po = _create_po(client, headers, customer["customer_code"], [{"part_number": schedule["part_number"], "po_qty": 600}])

    candidates = client.get("/api/v1/po-matching/candidates", headers=headers, params={"po_line_id": po["lines"][0]["id"]}).json()
    match = next(c for c in candidates if c["schedule_id"] == schedule["id"])
    assert match["quantity_match"] == "PO_ABOVE_SCHEDULE"
    assert match["mismatch_message"] == "Quantity mismatch: PO is 100 above schedule"


# ---------------------------------------------------------------------------
# 11. Prevent OAR quantity above available PO quantity
# ---------------------------------------------------------------------------

def test_oar_quantity_cannot_exceed_available_po_quantity(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    po = _create_po(client, headers, customer["customer_code"], [{"part_number": "BRZ-BUSH-100", "po_qty": 300}])
    po_line_id = po["lines"][0]["id"]

    over = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": customer["customer_code"], "customer_name": customer["name"],
            "customer_po": po["po_number"], "part_number": "BRZ-BUSH-100",
            "po_quantity": 301, "max_batch_size": 301, "po_line_id": po_line_id,
        },
    )
    assert over.status_code == 400, over.text
    assert "exceeds the available unallocated PO quantity" in over.json()["detail"]

    within = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": customer["customer_code"], "customer_name": customer["name"],
            "customer_po": po["po_number"], "part_number": "BRZ-BUSH-100",
            "po_quantity": 300, "max_batch_size": 300, "po_line_id": po_line_id,
        },
    )
    assert within.status_code == 200, within.text

    lines = client.get("/api/v1/masters/pos", headers=headers, params={"customer_code": customer["customer_code"]}).json()
    line = lines[0]["lines"][0]
    assert line["allocated_qty"] == 300
    assert line["available_qty"] == 0


# ---------------------------------------------------------------------------
# 12. Prevent duplicate PO/OAR allocation (matching an already-matched schedule again)
# ---------------------------------------------------------------------------

def test_cannot_match_an_already_matched_schedule_again(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    schedule = _create_schedule(client, headers, customer["customer_code"], qty=200)
    _intake_schedule_oar(client, headers, customer["customer_code"], customer["name"], schedule)
    po1 = _create_po(client, headers, customer["customer_code"], [{"part_number": schedule["part_number"], "po_qty": 200}])
    first = client.post(
        "/api/v1/po-matching/match", headers=headers,
        json={"po_line_id": po1["lines"][0]["id"], "schedule_id": schedule["id"]},
    )
    assert first.status_code == 200, first.text

    po2 = _create_po(client, headers, customer["customer_code"], [{"part_number": schedule["part_number"], "po_qty": 200}])
    second = client.post(
        "/api/v1/po-matching/match", headers=headers,
        json={"po_line_id": po2["lines"][0]["id"], "schedule_id": schedule["id"]},
    )
    assert second.status_code == 400, second.text


# ---------------------------------------------------------------------------
# 13-14. Multiple schedules for same customer/part; multiple PO lines
# ---------------------------------------------------------------------------

def test_multiple_schedules_same_customer_and_part(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    s1 = _create_schedule(client, headers, customer["customer_code"], qty=200)
    s2 = _create_schedule(client, headers, customer["customer_code"], qty=300)
    _intake_schedule_oar(client, headers, customer["customer_code"], customer["name"], s1)
    _intake_schedule_oar(client, headers, customer["customer_code"], customer["name"], s2)

    dup = client.get(
        "/api/v1/po-matching/check-duplicate", headers=headers,
        params={"customer_code": customer["customer_code"], "part_number": s1["part_number"]},
    ).json()
    schedule_ids = {c["schedule_id"] for c in dup["candidates"]}
    assert {s1["id"], s2["id"]} <= schedule_ids


def test_multiple_po_lines_on_one_po(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    po = _create_po(client, headers, customer["customer_code"], [
        {"part_number": "BRZ-BUSH-100", "po_qty": 100},
        {"part_number": "BRZ-RING-250", "po_qty": 200},
    ])
    assert len(po["lines"]) == 2
    parts = {l["part_number"] for l in po["lines"]}
    assert parts == {"BRZ-BUSH-100", "BRZ-RING-250"}


# ---------------------------------------------------------------------------
# 15. Audit history preserved
# ---------------------------------------------------------------------------

def test_audit_history_recorded_for_schedule_po_and_match(client):
    headers = _auth(_login(client))
    customer = _create_customer(client, headers)
    schedule = _create_schedule(client, headers, customer["customer_code"], qty=500)
    _intake_schedule_oar(client, headers, customer["customer_code"], customer["name"], schedule)
    po = _create_po(client, headers, customer["customer_code"], [{"part_number": schedule["part_number"], "po_qty": 500}])
    client.post(
        "/api/v1/po-matching/match", headers=headers,
        json={"po_line_id": po["lines"][0]["id"], "schedule_id": schedule["id"]},
    )

    logs = client.get("/api/v1/admin/audit-logs", headers=headers, params={"limit": 500}).json()
    actions = {l["action"] for l in logs}
    assert "SCHEDULE_CREATED" in actions
    assert "PO_CREATED" in actions
    assert "PO_SCHEDULE_MATCHED" in actions


# ---------------------------------------------------------------------------
# 16. Existing plain OAR -> WO workflow remains completely unchanged
# ---------------------------------------------------------------------------

def test_existing_plain_oar_to_wo_workflow_unchanged(client):
    headers = _auth(_login(client))
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Flowserve Sanmar Ltd",
            "customer_po": f"PO-PLAIN-{uuid.uuid4().hex[:8]}", "part_number": "BRZ-BUSH-100",
            "po_quantity": 100, "max_batch_size": 100,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_type"] == "po"
    assert body["oar_po_status"] is None
    assert len(body["wos_created"]) == 1
    assert "Schedule-based" not in body["message"]


def test_non_planning_role_cannot_manage_masters_or_matching(client):
    store_token = _login(client, "STORE")
    headers = _auth(store_token)
    assert client.get("/api/v1/masters/customers", headers=headers).status_code == 403
    assert client.post("/api/v1/masters/schedules", headers=headers, json={
        "customer_code": "CUST-VALVE", "part_number": "BRZ-BUSH-100", "scheduled_qty": 10,
    }).status_code == 403
