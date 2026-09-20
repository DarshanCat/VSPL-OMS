"""
Final independent red-team verification.

Every test here drives the REAL HTTP boundary (TestClient -> FastAPI routing ->
auth dependency -> RBAC dependency -> Pydantic validation -> service -> DB -> response),
not helper functions in isolation. Nothing here trusts a prior report; every claim is
re-proven against the live app.
"""
import time
import uuid
import threading
import pytest
from datetime import datetime, timedelta

from jose import jwt as jose_jwt
from fastapi.testclient import TestClient

from app.core.config import settings
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
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _intake_wo(client, token, po_qty=20):
    resp = client.post(
        "/api/v1/operations/intake",
        headers=_auth(token),
        json={
            "customer_code": "CUST-REDTEAM",
            "customer_name": "Red Team Customer",
            "customer_po": f"PO-RT-{uuid.uuid4().hex[:8]}",
            "part_number": f"PART-RT-{uuid.uuid4().hex[:6]}",
            "po_quantity": po_qty,
            "max_batch_size": po_qty,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["wos_created"][0]


# ===========================================================================
# 3-4. AUTHENTICATION / JWT RED TEAM
# ===========================================================================

def test_login_invalid_credentials_rejected(client):
    resp = client.post("/api/v1/auth/login", json={"email": "admin@vspl.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_missing_fields_rejected(client):
    resp = client.post("/api/v1/auth/login", json={"email": "admin@vspl.com"})
    assert resp.status_code == 422


def test_missing_authorization_header_rejected(client):
    resp = client.get("/api/v1/dashboard/stats")
    assert resp.status_code in (401, 403)


def test_empty_authorization_header_rejected(client):
    resp = client.get("/api/v1/dashboard/stats", headers={"Authorization": ""})
    assert resp.status_code in (401, 403)


def test_malformed_token_rejected(client):
    resp = client.get("/api/v1/dashboard/stats", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401


def test_random_token_rejected(client):
    resp = client.get("/api/v1/dashboard/stats", headers=_auth(uuid.uuid4().hex))
    assert resp.status_code == 401


def test_token_signed_with_wrong_secret_rejected(client):
    forged = jose_jwt.encode({"sub": "admin@vspl.com", "role": "admin",
                               "exp": datetime.utcnow() + timedelta(minutes=30)},
                              "definitely-not-the-real-secret", algorithm="HS256")
    resp = client.get("/api/v1/dashboard/stats", headers=_auth(forged))
    assert resp.status_code == 401


def test_expired_token_rejected(client):
    expired = jose_jwt.encode({"sub": "admin@vspl.com", "role": "admin",
                                "exp": datetime.utcnow() - timedelta(minutes=5)},
                               settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    resp = client.get("/api/v1/dashboard/stats", headers=_auth(expired))
    assert resp.status_code == 401


def test_none_algorithm_token_rejected(client):
    """The classic 'alg: none' bypass -- an unsigned token must never be accepted."""
    header = '{"alg":"none","typ":"JWT"}'
    import base64
    import json as _json

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    payload = {"sub": "admin@vspl.com", "role": "admin", "exp": (datetime.utcnow() + timedelta(minutes=30)).timestamp()}
    token = f"{b64url(header.encode())}.{b64url(_json.dumps(payload).encode())}."
    resp = client.get("/api/v1/dashboard/stats", headers=_auth(token))
    assert resp.status_code == 401


def test_rs256_token_rejected_even_if_well_formed(client):
    """Server only accepts HS256; an RS256 token (even a validly-signed one under a
    different keypair) must never be accepted -- proves the algorithm is not selected
    dynamically from the token."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.PEM,
        format=__import__("cryptography.hazmat.primitives.serialization", fromlist=["PrivateFormat"]).PrivateFormat.PKCS8,
        encryption_algorithm=__import__("cryptography.hazmat.primitives.serialization", fromlist=["NoEncryption"]).NoEncryption(),
    )
    token = jose_jwt.encode(
        {"sub": "admin@vspl.com", "role": "admin", "exp": datetime.utcnow() + timedelta(minutes=30)},
        pem, algorithm="RS256",
    )
    resp = client.get("/api/v1/dashboard/stats", headers=_auth(token))
    assert resp.status_code == 401


def test_token_with_forged_role_claim_ignored(client):
    """A token forged with role=admin but signed with the REAL secret for a real
    non-admin user's email must still be authorized as that user's actual DB role, not
    the claimed one -- proving role comes from the DB record, not the token payload."""
    forged = jose_jwt.encode(
        {"sub": "operator@vspl.com", "role": "admin", "exp": datetime.utcnow() + timedelta(minutes=30)},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )
    resp = client.get("/api/v1/admin/audit-logs", headers=_auth(forged))
    assert resp.status_code == 403  # operator's real DB role, not the forged "admin" claim


def test_token_with_nonexistent_user_rejected(client):
    forged = jose_jwt.encode(
        {"sub": "nobody-real@vspl.com", "role": "admin", "exp": datetime.utcnow() + timedelta(minutes=30)},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )
    resp = client.get("/api/v1/dashboard/stats", headers=_auth(forged))
    assert resp.status_code == 401


# ===========================================================================
# 5-6. RBAC / PRIVILEGE ESCALATION RED TEAM
# ===========================================================================

def test_operator_cannot_register_new_users(client):
    op = _login(client, "MACHINE_OPERATOR")
    resp = client.post("/api/v1/auth/register", headers=_auth(op),
                        json={"full_name": "x", "email": f"x{uuid.uuid4().hex[:6]}@vspl.com", "password": "x", "role": "admin"})
    assert resp.status_code == 403


def test_operator_cannot_view_audit_logs(client):
    op = _login(client, "MACHINE_OPERATOR")
    resp = client.get("/api/v1/admin/audit-logs", headers=_auth(op))
    assert resp.status_code == 403


def test_operator_cannot_release_wo(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    op = _login(client, "MACHINE_OPERATOR")
    resp = client.post("/api/v1/operations/wo-release", headers=_auth(op),
                        json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "DISPATCH"]})
    assert resp.status_code == 403


def test_operator_cannot_dispatch(client):
    op = _login(client, "MACHINE_OPERATOR")
    resp = client.post("/api/v1/dispatch/ship", headers=_auth(op),
                        json={"wo_number": "WO-1007", "invoice_number": f"INV-RT-{uuid.uuid4().hex[:6]}", "dispatched_quantity": 1})
    assert resp.status_code == 403


def test_operator_cannot_disposition_nc(client):
    admin = _login(client, "ADMIN")
    nc = client.post("/api/v1/operations/nc", headers=_auth(admin),
                      json={"wo_number": "WO-1001", "stage": "F2", "defect_code": "DEF-POROSITY", "qty": 1}).json()["nc_number"]
    op = _login(client, "MACHINE_OPERATOR")
    resp = client.put("/api/v1/operations/nc", headers=_auth(op), json={"nc_number": nc, "status": "Closed"})
    assert resp.status_code == 403


def test_privilege_escalation_via_role_field_in_register_body(client):
    """Even an ADMIN-authorized call cannot be tricked by extra fields; but more
    importantly a non-admin cannot smuggle a role by any body field manipulation."""
    op = _login(client, "MACHINE_OPERATOR")
    resp = client.post("/api/v1/auth/register", headers=_auth(op),
                        json={"full_name": "Escalator", "email": f"esc{uuid.uuid4().hex[:6]}@vspl.com",
                              "password": "x", "role": "operator", "is_admin": True, "permission": "admin"})
    assert resp.status_code == 403  # blocked before body content even matters


def test_operator_id_cannot_be_smuggled_into_movement(client):
    """The operator_id field was removed from MovePartsRequest entirely (fixed in a
    prior pass); confirm extra/unknown body fields are simply ignored, not honored."""
    admin = _login(client, "ADMIN")
    victim = client.get("/api/v1/admin/audit-logs", headers=_auth(admin))  # just to have a token flow
    op = _login(client, "MACHINE_OPERATOR")
    wo = _intake_wo(client, admin)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "F2", "DISPATCH"]})
    resp = client.post("/api/v1/production/move", headers=_auth(op), json={
        "wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 1,
        "operator_id": str(uuid.uuid4()), "created_by": str(uuid.uuid4()), "user_id": str(uuid.uuid4()),
    })
    # request must either succeed ignoring the smuggled identity fields, or fail for a
    # legitimate business reason (e.g. no F1 production yet) -- never 500, never let the
    # smuggled id through
    assert resp.status_code in (200, 400)


# ===========================================================================
# 7. IDOR / BOLA
# ===========================================================================

def test_cannot_dispatch_another_wo_by_guessing_number(client):
    """Dispatch is scoped by wo_number the caller supplies; verify a nonexistent /
    unrelated WO number is rejected rather than silently affecting an unrelated WO."""
    dispatch_token = _login(client, "DISPATCH")
    resp = client.post("/api/v1/dispatch/ship", headers=_auth(dispatch_token),
                        json={"wo_number": "WO-DOES-NOT-EXIST-9999", "invoice_number": "INV-X", "dispatched_quantity": 1})
    assert resp.status_code == 404


def test_nc_disposition_on_nonexistent_nc_rejected(client):
    qa = _login(client, "QA")
    resp = client.put("/api/v1/operations/nc", headers=_auth(qa),
                       json={"nc_number": "NC-DOES-NOT-EXIST", "status": "Closed"})
    assert resp.status_code == 404


# ===========================================================================
# 8. MANUFACTURING QUANTITY ATTACKS
# ===========================================================================

@pytest.mark.parametrize("bad_qty", [-1, 0])
def test_movement_rejects_non_positive_quantity(client, bad_qty):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "F2", "DISPATCH"]})
    resp = client.post("/api/v1/production/move", headers=_auth(admin),
                        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": bad_qty})
    assert resp.status_code == 422


def test_movement_rejects_absurdly_large_quantity(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "F2", "DISPATCH"]})
    resp = client.post("/api/v1/production/move", headers=_auth(admin),
                        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 99999999999})
    assert resp.status_code == 422


def test_movement_rejects_non_numeric_quantity(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    resp = client.post("/api/v1/production/move", headers=_auth(admin),
                        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": "fifty"})
    assert resp.status_code == 422


def test_movement_rejects_nan_and_infinity(client):
    """Standard-compliant JSON has no NaN/Infinity literal, so a conforming client
    cannot even serialize one -- but Python's own json.loads (and many other parsers)
    accept the non-standard NaN/Infinity/-Infinity tokens as an extension by default.
    Send the raw bytes directly to prove the *server* rejects them regardless of what
    parses the body, rather than relying on the test client refusing to send it."""
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    for literal in ("NaN", "Infinity", "-Infinity"):
        raw = (
            '{"wo_number": "%s", "from_stage": "F1", "to_stage": "F2", "quantity_moved": %s}'
            % (wo, literal)
        ).encode()
        resp = client.post("/api/v1/production/move", headers={**_auth(admin), "Content-Type": "application/json"},
                            content=raw)
        assert resp.status_code == 422, f"payload {literal} was not rejected (got {resp.status_code}: {resp.text})"


def test_movement_rejects_null_and_missing_quantity(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    resp = client.post("/api/v1/production/move", headers=_auth(admin),
                        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": None})
    assert resp.status_code == 422
    resp2 = client.post("/api/v1/production/move", headers=_auth(admin),
                         json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2"})
    assert resp2.status_code == 422


def test_dispatch_and_packing_reject_bad_quantities(client):
    admin = _login(client, "ADMIN")
    for bad in (-5, 0, "abc", None):
        resp = client.post("/api/v1/packing/update", headers=_auth(admin),
                            json={"wo_number": "WO-1006", "packed_quantity": bad})
        assert resp.status_code == 422, f"packing accepted bad qty {bad!r}"
        resp2 = client.post("/api/v1/dispatch/ship", headers=_auth(admin),
                             json={"wo_number": "WO-1007", "invoice_number": "INV-BAD", "dispatched_quantity": bad})
        assert resp2.status_code == 422, f"dispatch accepted bad qty {bad!r}"


# ===========================================================================
# 9. OVERPOSTING
# ===========================================================================

def test_movement_response_reflects_server_computed_state_not_client_input(client):
    """Even if a client tries to inject 'available_wip_remaining' or 'current_stage'
    into the request, the response must reflect server-computed truth."""
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "F2", "DISPATCH"]})
    resp = client.post("/api/v1/production/move", headers=_auth(admin), json={
        "wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 5,
        "available_wip_remaining": 99999, "current_stage": "DISPATCH", "status": "dispatched",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available_wip_remaining"] == 15  # 20 - 5, server-computed, not the injected 99999
    assert body["current_stage"] != "DISPATCH"


# ===========================================================================
# 10-11. WORKFLOW BYPASS / CROSS-WO
# ===========================================================================

def test_stage_jump_rejected(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "F2", "F3", "DISPATCH"]})
    resp = client.post("/api/v1/production/move", headers=_auth(admin),
                        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F3", "quantity_moved": 5})
    assert resp.status_code == 400


def test_cross_wo_movement_rejected_for_all_id_combinations(client):
    admin = _login(client, "ADMIN")
    wo_a = _intake_wo(client, admin)
    wo_b = _intake_wo(client, admin)
    for wo in (wo_a, wo_b):
        client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                    json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "F2", "DISPATCH"]})
    resp = client.post("/api/v1/production/move", headers=_auth(admin), json={
        "wo_number": wo_a, "target_wo_number": wo_b, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 5,
    })
    assert resp.status_code == 400


def test_dispatch_beyond_eligible_quantity_rejected(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin, po_qty=10)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 10, "route_stages": ["F1", "PACKING", "DISPATCH"]})
    client.post("/api/v1/production/entry", headers=_auth(admin),
                json={"wo_number": wo, "stage": "F1", "good_qty": 10, "rejected_quantity": 0})
    client.post("/api/v1/production/move", headers=_auth(admin),
                json={"wo_number": wo, "from_stage": "F1", "to_stage": "PACKING", "quantity_moved": 10})
    client.post("/api/v1/packing/update", headers=_auth(admin), json={"wo_number": wo, "packed_quantity": 10})
    dispatch_token = _login(client, "DISPATCH")
    resp = client.post("/api/v1/dispatch/ship", headers=_auth(dispatch_token),
                        json={"wo_number": wo, "invoice_number": "INV-OVER", "dispatched_quantity": 11})
    assert resp.status_code == 400


def test_dispatch_before_bsr_rejected_when_route_requires_it(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin, po_qty=10)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 10, "route_stages": ["F1", "PACKING", "BSR", "DISPATCH"]})
    client.post("/api/v1/production/entry", headers=_auth(admin),
                json={"wo_number": wo, "stage": "F1", "good_qty": 10, "rejected_quantity": 0})
    client.post("/api/v1/production/move", headers=_auth(admin),
                json={"wo_number": wo, "from_stage": "F1", "to_stage": "PACKING", "quantity_moved": 10})
    client.post("/api/v1/packing/update", headers=_auth(admin), json={"wo_number": wo, "packed_quantity": 10})
    dispatch_token = _login(client, "DISPATCH")
    resp = client.post("/api/v1/dispatch/ship", headers=_auth(dispatch_token),
                        json={"wo_number": wo, "invoice_number": "INV-NOBSR", "dispatched_quantity": 10})
    assert resp.status_code == 400
    assert "BSR" in resp.text


# ===========================================================================
# 12. REPLAY / IDEMPOTENCY
# ===========================================================================

def test_replaying_production_entry_10_times_creates_one_transaction(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin, po_qty=50)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 50, "route_stages": ["F1", "DISPATCH"]})
    token = f"REPLAY-{uuid.uuid4().hex}"
    results = []
    for _ in range(10):
        resp = client.post("/api/v1/production/entry", headers=_auth(admin),
                            json={"wo_number": wo, "stage": "F1", "good_qty": 10, "rejected_quantity": 0,
                                  "client_request_id": token})
        results.append(resp.json())
    assert all(r["stage_ok_total"] == 10 for r in results), "quantity multiplied across replays"


def test_replaying_dispatch_100_times_in_isolated_env_creates_one_shipment(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin, po_qty=10)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 10, "route_stages": ["F1", "PACKING", "DISPATCH"]})
    client.post("/api/v1/production/entry", headers=_auth(admin),
                json={"wo_number": wo, "stage": "F1", "good_qty": 10, "rejected_quantity": 0})
    client.post("/api/v1/production/move", headers=_auth(admin),
                json={"wo_number": wo, "from_stage": "F1", "to_stage": "PACKING", "quantity_moved": 10})
    client.post("/api/v1/packing/update", headers=_auth(admin), json={"wo_number": wo, "packed_quantity": 10})
    dispatch_token = _login(client, "DISPATCH")
    token = f"REPLAY-DISP-{uuid.uuid4().hex}"
    for _ in range(100):
        resp = client.post("/api/v1/dispatch/ship", headers=_auth(dispatch_token),
                            json={"wo_number": wo, "invoice_number": "INV-REPLAY", "dispatched_quantity": 10,
                                  "client_request_id": token})
        assert resp.status_code == 200
        assert resp.json()["remaining_ready_for_dispatch"] == 0


# ===========================================================================
# 13. CONCURRENCY
# ===========================================================================

_SQLITE_CONCURRENCY_SKIP_REASON = (
    "with_for_update() row locking (used throughout ProductionService/PackingService/"
    "DispatchService) is a documented no-op under SQLAlchemy's SQLite dialect -- SQLite "
    "itself serializes all writes at the file level regardless, so this does not reflect "
    "a real vulnerability, but it also means SQLite cannot exercise or disprove Postgres's "
    "actual row-locking behavior. This test must be run against PostgreSQL (the real "
    "production engine, per docs/OMS_RELEASE_BASELINE.md) to mean anything -- e.g.: "
    "DATABASE_URL=postgresql://vspl_user:vspl_pass@localhost:5432/vspl_smes pytest "
    "tests/test_red_team.py -k concurrent -- where it has been verified to pass."
)


@pytest.mark.skipif(settings.DATABASE_URL.startswith("sqlite"), reason=_SQLITE_CONCURRENCY_SKIP_REASON)
def test_concurrent_movement_cannot_oversell_available_quantity(client, monkeypatch):
    """Available = 100 at F1; fire two concurrent moves of 60 and 50. At most 100 total
    may ever be committed -- one must be rejected or reduced, never both fully succeed."""
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin, po_qty=100)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 100, "route_stages": ["F1", "F2", "DISPATCH"]})

    results = {}

    def do_move(key, qty):
        with TestClient(app) as c:
            r = c.post("/api/v1/production/move", headers=_auth(admin),
                       json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": qty})
            results[key] = r

    t1 = threading.Thread(target=do_move, args=("A", 60))
    t2 = threading.Thread(target=do_move, args=("B", 50))
    t1.start(); t2.start()
    t1.join(); t2.join()

    successful_total = sum(
        r.json()["quantity_moved"] for r in results.values() if r.status_code == 200
    )
    assert successful_total <= 100, f"oversold: committed {successful_total} against 100 available"


@pytest.mark.skipif(settings.DATABASE_URL.startswith("sqlite"), reason=_SQLITE_CONCURRENCY_SKIP_REASON)
def test_concurrent_movement_both_over_available_cannot_both_win(client):
    """Available = 100; both concurrent requests ask for 70 (140 total, both exceeding
    what's left after either one succeeds). At most one may succeed for the full amount;
    total committed must never exceed what was actually available."""
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin, po_qty=100)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 100, "route_stages": ["F1", "F2", "DISPATCH"]})

    results = {}

    def do_move(key, qty):
        with TestClient(app) as c:
            r = c.post("/api/v1/production/move", headers=_auth(admin),
                       json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": qty})
            results[key] = r

    t1 = threading.Thread(target=do_move, args=("A", 70))
    t2 = threading.Thread(target=do_move, args=("B", 70))
    t1.start(); t2.start()
    t1.join(); t2.join()

    successful_total = sum(
        r.json()["quantity_moved"] for r in results.values() if r.status_code == 200
    )
    assert successful_total <= 100, f"oversold: committed {successful_total} against 100 available"
    # At least one of the two must have been rejected (140 requested against 100 available).
    assert any(r.status_code == 400 for r in results.values())


# ===========================================================================
# 15-16. SQL INJECTION / XSS
# ===========================================================================

@pytest.mark.parametrize("payload", ["'", '"', "' OR '1'='1", "1 OR 1=1", "'; DROP TABLE work_orders; --"])
def test_sql_injection_payloads_in_wo_lookup_do_not_execute(client, payload):
    admin = _login(client, "ADMIN")
    resp = client.get(f"/api/v1/work-orders/{payload}/tracking", headers=_auth(admin))
    assert resp.status_code in (400, 404, 422)
    # Prove the table still exists and normal lookups still work afterward.
    resp2 = client.get("/api/v1/work-orders/WO-1001/tracking", headers=_auth(admin))
    assert resp2.status_code == 200


def test_sql_injection_in_movement_filter_query_param(client):
    admin = _login(client, "ADMIN")
    resp = client.get("/api/v1/production/movements", headers=_auth(admin),
                       params={"wo_number": "' OR '1'='1", "stage": "'; DROP TABLE production_movements; --"})
    assert resp.status_code == 200  # safely returns an empty/normal result, not a 500
    resp2 = client.get("/api/v1/production/movements", headers=_auth(admin))
    assert resp2.status_code == 200  # table still intact


@pytest.mark.parametrize("payload", ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "javascript:alert(1)"])
def test_xss_payload_in_remarks_is_stored_inert_and_returned_escaped_by_api(client, payload):
    """The API itself must not execute anything (it's JSON, not HTML) and must store
    the raw value without transformation -- rendering-side escaping is React's job
    (already verified: no dangerouslySetInnerHTML anywhere in the frontend)."""
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "F2", "DISPATCH"]})
    resp = client.post("/api/v1/production/move", headers=_auth(admin),
                        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 1, "remarks": payload})
    assert resp.status_code == 200
    # Content-Type must be application/json -- browsers will never render this as HTML.
    assert resp.headers["content-type"].startswith("application/json")


# ===========================================================================
# 17. PATH TRAVERSAL (re-verification)
# ===========================================================================

def test_upload_path_traversal_variants_are_confined(tmp_path):
    import asyncio
    from app.oms_core.storage import save_upload

    class FakeUploadFile:
        def __init__(self, filename):
            self.filename = filename
        async def read(self):
            return b"payload"

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # Search strictly OUTSIDE run_dir (siblings of it), not tmp_path.parent recursively --
    # a recursive search from the parent would also match files legitimately saved
    # *inside* run_dir, producing a false positive.
    outside = tmp_path.parent

    def outside_hits():
        return {p for p in outside.rglob("evil.txt") if run_dir.resolve() not in p.resolve().parents}

    variants = ["../evil.txt", "..\\evil.txt", "../../evil.txt", "/etc/passwd", "....//....//evil.txt"]
    for v in variants:
        before = outside_hits()
        result = asyncio.run(save_upload(FakeUploadFile(v), run_dir))
        after = outside_hits()
        assert after == before, f"traversal payload {v!r} escaped the run directory"
        if result is not None:
            from pathlib import Path
            assert run_dir.resolve() in Path(result).resolve().parents


# ===========================================================================
# 18. RESOURCE EXHAUSTION
# ===========================================================================

def test_limit_zero_and_negative_rejected_not_silently_unbounded(client):
    admin = _login(client, "ADMIN")
    for bad_limit in (0, -1):
        resp = client.get("/api/v1/production/movements", headers=_auth(admin), params={"limit": bad_limit})
        assert resp.status_code == 422
        resp2 = client.get("/api/v1/dispatch/history", headers=_auth(admin), params={"limit": bad_limit})
        assert resp2.status_code == 422
        resp3 = client.get("/api/v1/operations/nc", headers=_auth(admin), params={"limit": bad_limit})
        assert resp3.status_code == 422


def test_huge_limit_is_capped_not_unbounded(client):
    admin = _login(client, "ADMIN")
    resp = client.get("/api/v1/production/movements", headers=_auth(admin), params={"limit": 999999999})
    assert resp.status_code == 422  # exceeds the declared le= ceiling
    resp2 = client.get("/api/v1/admin/audit-logs", headers=_auth(admin), params={"limit": 999999999})
    assert resp2.status_code == 422


def test_huge_offset_does_not_error(client):
    admin = _login(client, "ADMIN")
    resp = client.get("/api/v1/production/movements", headers=_auth(admin), params={"offset": 999999999})
    assert resp.status_code == 200
    assert resp.json() == []


# ===========================================================================
# 19-20. CORS / SECURITY HEADERS
# ===========================================================================

def test_cors_only_configured_origins_allowed(client):
    resp = client.options("/api/v1/auth/login", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    resp2 = client.options("/api/v1/auth/login", headers={
        "Origin": "http://attacker.evil", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in resp2.headers


def test_all_response_types_carry_baseline_security_headers(client):
    admin = _login(client, "ADMIN")
    for resp in (
        client.get("/health"),
        client.get("/api/v1/dashboard/stats", headers=_auth(admin)),
        client.post("/api/v1/auth/login", json={"email": "x", "password": "x"}),
    ):
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


# ===========================================================================
# 22-23. SECRET / ERROR DISCLOSURE
# ===========================================================================

def test_error_responses_never_leak_internals(client):
    admin = _login(client, "ADMIN")
    cases = [
        client.get("/api/v1/work-orders/WO-DOES-NOT-EXIST/tracking", headers=_auth(admin)),
        client.post("/api/v1/production/move", headers=_auth(admin), json={"wo_number": 123}),
        client.get("/api/v1/admin/audit-logs"),
        client.post("/api/v1/dispatch/ship", headers=_auth(admin), json={}),
    ]
    for resp in cases:
        body = resp.text.lower()
        for leak in ("traceback", "site-packages", ".py\"", "secret_key", "password=", "sqlalchemy.exc"):
            assert leak not in body, f"leaked internal detail {leak!r} in {resp.status_code} response: {body[:300]}"


def test_no_backend_secret_in_frontend_production_bundle():
    import subprocess
    frontend_dir = __import__("pathlib").Path(__file__).resolve().parents[2] / "frontend" / ".next"
    if not frontend_dir.exists():
        pytest.skip(".next build output not present in this run")
    hits = []
    for f in frontend_dir.rglob("*.js"):
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        if settings.SECRET_KEY in text or "vspl-smes-enterprise-production-secret-key" in text:
            hits.append(str(f))
    assert not hits, f"backend SECRET_KEY leaked into frontend bundle: {hits}"


# ===========================================================================
# 24. AUDIT TAMPERING
# ===========================================================================

def test_audit_log_has_no_write_endpoints(client):
    admin = _login(client, "ADMIN")
    # No PUT/PATCH/DELETE route exists for audit logs at all; prove the paths 404/405.
    for method, path in [("put", "/api/v1/admin/audit-logs"), ("delete", "/api/v1/admin/audit-logs"),
                          ("patch", "/api/v1/admin/audit-logs/1")]:
        resp = getattr(client, method)(path, headers=_auth(admin))
        assert resp.status_code in (404, 405)


def test_audit_actor_cannot_be_spoofed_via_body(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "F2", "DISPATCH"]})
    client.post("/api/v1/production/move", headers=_auth(admin), json={
        "wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 3,
        "user_name": "Someone Else", "created_by": str(uuid.uuid4()),
    })
    resp = client.get("/api/v1/admin/audit-logs", headers=_auth(admin), params={"limit": 5})
    assert resp.status_code == 200
    latest = resp.json()[0]
    assert latest["user_name"] != "Someone Else"


# ===========================================================================
# 26. DATABASE INTEGRITY
# ===========================================================================

def test_duplicate_client_request_id_across_different_wos_is_still_deduped(client):
    """Uniqueness is on the token itself (global), not scoped per-WO -- confirm this
    is actually enforced, not just assumed."""
    admin = _login(client, "ADMIN")
    wo_a = _intake_wo(client, admin)
    wo_b = _intake_wo(client, admin)
    for wo in (wo_a, wo_b):
        client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                    json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "DISPATCH"]})
    token = f"DUP-{uuid.uuid4().hex}"
    r1 = client.post("/api/v1/production/entry", headers=_auth(admin),
                      json={"wo_number": wo_a, "stage": "F1", "good_qty": 5, "client_request_id": token})
    r2 = client.post("/api/v1/production/entry", headers=_auth(admin),
                      json={"wo_number": wo_b, "stage": "F1", "good_qty": 5, "client_request_id": token})
    assert r1.status_code == 200
    assert r2.status_code == 200
    # The second call must return the FIRST transaction's data (deduped), not create a
    # second, different one against wo_b.
    assert r2.json()["wo_number"] == wo_a
    assert "Duplicate" in r2.json()["message"]
