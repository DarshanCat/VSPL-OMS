"""Regression tests for company email domain restrictions during user creation.
Validates:
1. @vijayspheroidals.com -> accepted
2. @vijayspheroidals.onmicrosoft.com -> accepted
3. Uppercase domain -> accepted
4. Gmail (@gmail.com) -> rejected
5. Outlook (@outlook.com) -> rejected
6. Yahoo (@yahoo.com) -> rejected
7. @vspl.com -> rejected
8. Attacker lookalike domain -> rejected
9. Whitespace around email -> correctly normalized and trimmed
10. Existing users with other domains remain unchanged and functional
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app
from app.core.database import SessionLocal
from app.models.user import User, UserRole
from app.core.security import ALLOWED_EMAIL_DOMAINS, validate_company_email
from fastapi import HTTPException

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


# ---------------------------------------------------------------------------
# Unit tests for validate_company_email helper
# ---------------------------------------------------------------------------
def test_validator_allowed_domains():
    assert validate_company_email("user@vijayspheroidals.com") == "user@vijayspheroidals.com"
    assert validate_company_email("user.name@vijayspheroidals.onmicrosoft.com") == "user.name@vijayspheroidals.onmicrosoft.com"
    assert validate_company_email("  USER@VIJAYSPHEROIDALS.COM  ") == "USER@vijayspheroidals.com"
    assert validate_company_email("USER@VIJAYSPHEROIDALS.ONMICROSOFT.COM") == "USER@vijayspheroidals.onmicrosoft.com"


@pytest.mark.parametrize("invalid_email", [
    "user@gmail.com",
    "user@outlook.com",
    "user@yahoo.com",
    "user@vspl.com",
    "user@vijayspheroidals.com.attacker.com",
    "user@vijayspheroidals.onmicrosoft.com.attacker.com",
    "user@attacker-vijayspheroidals.com",
    "user@sub.vijayspheroidals.com",
    "not-an-email",
    "@vijayspheroidals.com",
    "user@",
    "",
])
def test_validator_rejects_invalid_domains(invalid_email):
    with pytest.raises(HTTPException) as exc_info:
        validate_company_email(invalid_email)
    assert exc_info.value.status_code == 400
    assert "Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed." in exc_info.value.detail


# ---------------------------------------------------------------------------
# Integration tests via POST /api/v1/users
# ---------------------------------------------------------------------------

# 1. @vijayspheroidals.com -> accepted
def test_create_user_allowed_domain_primary(client):
    admin_token = _login(client, "ADMIN")
    unique_id = uuid.uuid4().hex[:8]
    email = f"emp-{unique_id}@vijayspheroidals.com"

    resp = client.post(
        "/api/v1/users", headers=_auth(admin_token),
        json={"full_name": "Primary Domain Employee", "email": email, "department": "Operations", "role": "planner"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user"]["email"] == email


# 2. @vijayspheroidals.onmicrosoft.com -> accepted
def test_create_user_allowed_domain_onmicrosoft(client):
    admin_token = _login(client, "ADMIN")
    unique_id = uuid.uuid4().hex[:8]
    email = f"emp-{unique_id}@vijayspheroidals.onmicrosoft.com"

    resp = client.post(
        "/api/v1/users", headers=_auth(admin_token),
        json={"full_name": "Microsoft Domain Employee", "email": email, "department": "IT", "role": "qa"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user"]["email"] == email


# 3. Uppercase domain -> accepted and normalized
def test_create_user_uppercase_domain_accepted(client):
    admin_token = _login(client, "ADMIN")
    unique_id = uuid.uuid4().hex[:8]
    email = f"EMP-{unique_id}@VIJAYSPHEROIDALS.COM"

    resp = client.post(
        "/api/v1/users", headers=_auth(admin_token),
        json={"full_name": "Uppercase Employee", "email": email, "department": "Planning", "role": "planner"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user"]["email"] == f"EMP-{unique_id}@vijayspheroidals.com"


# 4. Gmail -> rejected
def test_create_user_gmail_rejected(client):
    admin_token = _login(client, "ADMIN")
    resp = client.post(
        "/api/v1/users", headers=_auth(admin_token),
        json={"full_name": "Gmail User", "email": f"emp-{uuid.uuid4().hex[:8]}@gmail.com", "role": "store"},
    )
    assert resp.status_code == 400, resp.text
    assert "Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed." in resp.json()["detail"]


# 5. Outlook -> rejected
def test_create_user_outlook_rejected(client):
    admin_token = _login(client, "ADMIN")
    resp = client.post(
        "/api/v1/users", headers=_auth(admin_token),
        json={"full_name": "Outlook User", "email": f"emp-{uuid.uuid4().hex[:8]}@outlook.com", "role": "store"},
    )
    assert resp.status_code == 400, resp.text
    assert "Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed." in resp.json()["detail"]


# 6. Yahoo -> rejected
def test_create_user_yahoo_rejected(client):
    admin_token = _login(client, "ADMIN")
    resp = client.post(
        "/api/v1/users", headers=_auth(admin_token),
        json={"full_name": "Yahoo User", "email": f"emp-{uuid.uuid4().hex[:8]}@yahoo.com", "role": "store"},
    )
    assert resp.status_code == 400, resp.text
    assert "Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed." in resp.json()["detail"]


# 7. @vspl.com -> rejected
def test_create_user_vspl_domain_rejected(client):
    admin_token = _login(client, "ADMIN")
    resp = client.post(
        "/api/v1/users", headers=_auth(admin_token),
        json={"full_name": "Legacy Domain Attempt", "email": f"emp-{uuid.uuid4().hex[:8]}@vspl.com", "role": "store"},
    )
    assert resp.status_code == 400, resp.text
    assert "Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed." in resp.json()["detail"]


# 8. Attacker lookalike domain -> rejected
def test_create_user_lookalike_attacker_domain_rejected(client):
    admin_token = _login(client, "ADMIN")
    lookalikes = [
        f"emp-{uuid.uuid4().hex[:8]}@vijayspheroidals.com.attacker.com",
        f"emp-{uuid.uuid4().hex[:8]}@vijayspheroidals.onmicrosoft.com.attacker.com",
        f"emp-{uuid.uuid4().hex[:8]}@attacker-vijayspheroidals.com",
        f"emp-{uuid.uuid4().hex[:8]}@fakevijayspheroidals.com",
    ]
    for lookalike in lookalikes:
        resp = client.post(
            "/api/v1/users", headers=_auth(admin_token),
            json={"full_name": "Attacker", "email": lookalike, "role": "planner"},
        )
        assert resp.status_code == 400, f"Expected rejection for {lookalike}, got {resp.status_code}"
        assert "Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed." in resp.json()["detail"]


# 9. Whitespace around email -> correctly normalized and trimmed
def test_create_user_whitespace_normalized(client):
    admin_token = _login(client, "ADMIN")
    unique_id = uuid.uuid4().hex[:8]
    email_with_spaces = f"   emp-{unique_id}@vijayspheroidals.com   "

    resp = client.post(
        "/api/v1/users", headers=_auth(admin_token),
        json={"full_name": "Spaces Employee", "email": email_with_spaces, "department": "Logistics", "role": "dispatch"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user"]["email"] == f"emp-{unique_id}@vijayspheroidals.com"


# 10. Existing users with other domains remain unchanged and functional
def test_existing_users_with_other_domains_remain_functional(client):
    # Seeded admin has @vspl.com
    admin_token = _login(client, "ADMIN")
    assert admin_token is not None

    # Seeded planner has @vspl.com
    planner_token = _login(client, "PLANNER")
    assert planner_token is not None

    # Can list existing users (which contain @vspl.com users)
    users = client.get("/api/v1/users", headers=_auth(admin_token)).json()
    assert any(u["email"] == "admin@vspl.com" for u in users)
    assert any(u["email"] == "planner@vspl.com" for u in users)

    # Can fetch identity for existing user with legacy domain
    me = client.get("/api/v1/auth/me", headers=_auth(planner_token)).json()
    assert me["email"] == "planner@vspl.com"
