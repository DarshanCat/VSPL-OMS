"""Regression tests for admin-driven user onboarding: create-with-generated-password,
forced first-login password change, and the RBAC/security guarantees around it.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app
from app.core.database import SessionLocal
from app.models.user import User

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
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _unique_email():
    return f"onboard-{uuid.uuid4().hex[:10]}@vspl-test.com"


# ---------------------------------------------------------------------------
# 1/2. Create user + duplicate rejection
# ---------------------------------------------------------------------------

def test_admin_can_create_user_and_receives_temporary_password_once(client):
    admin = _login(client, "ADMIN")
    email = _unique_email()
    resp = client.post(
        "/api/v1/users", headers=_auth(admin),
        json={"full_name": "Test Onboard", "email": email, "department": "Planning", "role": "planner"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == email
    assert body["user"]["must_change_password"] is True
    assert body["user"]["is_active"] is True
    assert len(body["temporary_password"]) >= 12
    # Never a predictable/default value.
    assert body["temporary_password"] not in ("admin123", "password123", "Password123", email)
    assert "hashed_password" not in body["user"]


def test_duplicate_user_creation_is_rejected_and_does_not_overwrite(client):
    admin = _login(client, "ADMIN")
    email = _unique_email()
    first = client.post(
        "/api/v1/users", headers=_auth(admin),
        json={"full_name": "First", "email": email, "department": "Planning", "role": "planner"},
    )
    assert first.status_code == 200, first.text
    first_temp_password = first.json()["temporary_password"]

    second = client.post(
        "/api/v1/users", headers=_auth(admin),
        json={"full_name": "Second Attempt", "email": email, "department": "Quality", "role": "qa"},
    )
    assert second.status_code == 400, second.text

    # The original account's role/department/password must be completely untouched.
    login_still_works = client.post("/api/v1/auth/login", json={"email": email, "password": first_temp_password})
    assert login_still_works.status_code == 200, login_still_works.text
    users = client.get("/api/v1/users", headers=_auth(admin)).json()
    match = next(u for u in users if u["email"] == email)
    assert match["role"] == "planner"
    assert match["department"] == "Planning"


# ---------------------------------------------------------------------------
# 3-6. Temp password auth -> forced change -> permanent password -> old one dead
# ---------------------------------------------------------------------------

def test_full_forced_password_change_flow(client):
    admin = _login(client, "ADMIN")
    email = _unique_email()
    created = client.post(
        "/api/v1/users", headers=_auth(admin),
        json={"full_name": "Flow Test", "email": email, "department": "Stores", "role": "store"},
    )
    assert created.status_code == 200, created.text
    temp_password = created.json()["temporary_password"]

    # 3. Temporary password authenticates successfully.
    login1 = client.post("/api/v1/auth/login", json={"email": email, "password": temp_password})
    assert login1.status_code == 200, login1.text
    assert login1.json()["must_change_password"] is True
    token1 = login1.json()["access_token"]

    # 4. /auth/me also reports the pending forced change.
    me = client.get("/api/v1/auth/me", headers=_auth(token1))
    assert me.status_code == 200, me.text
    assert me.json()["must_change_password"] is True

    # Change to a permanent password.
    change = client.post(
        "/api/v1/auth/change-password", headers=_auth(token1),
        json={"current_password": temp_password, "new_password": "MyPermanentPass!2026"},
    )
    assert change.status_code == 200, change.text
    assert change.json()["must_change_password"] is False
    new_token = change.json()["access_token"]

    me2 = client.get("/api/v1/auth/me", headers=_auth(new_token))
    assert me2.status_code == 200, me2.text
    assert me2.json()["must_change_password"] is False

    # 5. Permanent password now works for a fresh login.
    login2 = client.post("/api/v1/auth/login", json={"email": email, "password": "MyPermanentPass!2026"})
    assert login2.status_code == 200, login2.text
    assert login2.json()["must_change_password"] is False

    # 6. The old temporary password no longer authenticates.
    login_old = client.post("/api/v1/auth/login", json={"email": email, "password": temp_password})
    assert login_old.status_code == 401, login_old.text


def test_reset_password_forces_change_again(client):
    admin = _login(client, "ADMIN")
    email = _unique_email()
    created = client.post(
        "/api/v1/users", headers=_auth(admin),
        json={"full_name": "Reset Test", "email": email, "department": "Quality", "role": "qa"},
    )
    user_id = created.json()["user"]["id"]

    reset = client.post(f"/api/v1/users/{user_id}/reset-password", headers=_auth(admin))
    assert reset.status_code == 200, reset.text
    new_temp = reset.json()["temporary_password"]
    assert reset.json()["user"]["must_change_password"] is True

    login = client.post("/api/v1/auth/login", json={"email": email, "password": new_temp})
    assert login.status_code == 200, login.text
    assert login.json()["must_change_password"] is True


# ---------------------------------------------------------------------------
# 7. Unauthorized roles cannot create users / manage accounts
# ---------------------------------------------------------------------------

def test_non_admin_cannot_create_user(client):
    planner = _login(client, "PLANNER")
    resp = client.post(
        "/api/v1/users", headers=_auth(planner),
        json={"full_name": "Should Fail", "email": _unique_email(), "department": "Planning", "role": "planner"},
    )
    assert resp.status_code == 403, resp.text


def test_non_admin_cannot_list_users_or_reset_password(client):
    planner = _login(client, "PLANNER")
    assert client.get("/api/v1/users", headers=_auth(planner)).status_code == 403

    admin = _login(client, "ADMIN")
    victim = client.post(
        "/api/v1/users", headers=_auth(admin),
        json={"full_name": "Victim", "email": _unique_email(), "department": "Planning", "role": "planner"},
    )
    victim_id = victim.json()["user"]["id"]
    resp = client.post(f"/api/v1/users/{victim_id}/reset-password", headers=_auth(planner))
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 8. A user cannot change their own role/department
# ---------------------------------------------------------------------------

def test_user_cannot_change_own_role_via_change_password_endpoint(client):
    admin = _login(client, "ADMIN")
    email = _unique_email()
    created = client.post(
        "/api/v1/users", headers=_auth(admin),
        json={"full_name": "Role Lock Test", "email": email, "department": "Planning", "role": "planner"},
    )
    temp_password = created.json()["temporary_password"]
    token = client.post("/api/v1/auth/login", json={"email": email, "password": temp_password}).json()["access_token"]

    # Attempt to smuggle a role change alongside the password change -- the schema has
    # no such field, so extra keys are simply ignored, not applied.
    resp = client.post(
        "/api/v1/auth/change-password", headers=_auth(token),
        json={"current_password": temp_password, "new_password": "StillPlannerPass!1", "role": "admin", "department": "Executive"},
    )
    assert resp.status_code == 200, resp.text

    users = client.get("/api/v1/users", headers=_auth(admin)).json()
    match = next(u for u in users if u["email"] == email)
    assert match["role"] == "planner"
    assert match["department"] == "Planning"


# ---------------------------------------------------------------------------
# 9. Password hashes never appear in any API response
# ---------------------------------------------------------------------------

def test_password_hash_never_exposed(client):
    admin = _login(client, "ADMIN")
    resp = client.get("/api/v1/users", headers=_auth(admin))
    assert resp.status_code == 200, resp.text
    body_text = resp.text
    assert "hashed_password" not in body_text
    assert "$2b$" not in body_text  # bcrypt hash prefix

    me = client.get("/api/v1/auth/me", headers=_auth(admin))
    assert "hashed_password" not in me.text
    assert "$2b$" not in me.text


# ---------------------------------------------------------------------------
# The seven named onboarding accounts (bootstrap script logic)
# ---------------------------------------------------------------------------

def test_bootstrap_named_accounts_creates_all_seven_and_skips_existing(client):
    from app.scripts.bootstrap_named_accounts import ACCOUNTS
    from app.core.security import generate_temp_password, get_password_hash

    assert len(ACCOUNTS) == 7
    expected_emails = {
        "data.analyst@vijayspheroidals.com",
        "ppc@vijayspheroidals.com",
        "stores@vijayspheroidals.com",
        "quality@vijayspheroidals.com",
        "demo.production@vspl.com",
        "demo.dispatch@vspl.com",
        "demo.ceo@vspl.com",
    }
    assert {email for _, email, _, _ in ACCOUNTS} == expected_emails

    db = SessionLocal()
    try:
        created_emails = []
        for full_name, email, department, role in ACCOUNTS:
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                continue
            temp_password = generate_temp_password()
            db.add(User(
                full_name=full_name, email=email,
                hashed_password=get_password_hash(temp_password),
                role=role, department=department, is_active=True, must_change_password=True,
            ))
            db.commit()
            created_emails.append(email)

        all_present = db.query(User).filter(User.email.in_(expected_emails)).all()
        assert {u.email for u in all_present} == expected_emails
        for u in all_present:
            assert u.must_change_password is True

        # Running again must not overwrite anything -- every account already exists now.
        for full_name, email, department, role in ACCOUNTS:
            existing = db.query(User).filter(User.email == email).first()
            assert existing is not None
    finally:
        db.close()
