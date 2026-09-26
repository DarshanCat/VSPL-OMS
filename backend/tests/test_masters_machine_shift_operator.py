"""Machine / Shift / Operator master CRUD + RBAC regression suite."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.core.security import hash_password, create_access_token
from app.models.user import User, UserRole

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    yield db
    db.close()


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        yield test_db
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(db, email, role):
    user = User(full_name=email.split("@")[0], email=email, hashed_password=hash_password("x"), role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}, user


# ---------------------------------------------------------------------------
# Machine
# ---------------------------------------------------------------------------

def test_machine_crud_and_rbac(client, test_db):
    admin_headers, _ = _auth(test_db, "admin.mach@vspl.com", UserRole.ADMIN)
    op_headers, _ = _auth(test_db, "op.mach@vspl.com", UserRole.MACHINE_OPERATOR)

    resp = client.post("/api/v1/masters/machines", json={
        "machine_code": "M-CC01", "machine_name": "Centrifugal Casting 1", "department": "Casting"
    }, headers=op_headers)
    assert resp.status_code == 403

    resp = client.post("/api/v1/masters/machines", json={
        "machine_code": "M-CC01", "machine_name": "Centrifugal Casting 1", "department": "Casting"
    }, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    machine_id = resp.json()["id"]
    assert resp.json()["is_active"] is True

    # Machine list is readable by any authenticated user (needed for production entry).
    resp = client.get("/api/v1/masters/machines", headers=op_headers)
    assert resp.status_code == 200
    assert any(m["machine_code"] == "M-CC01" for m in resp.json())

    resp = client.put("/api/v1/masters/machines", json={"id": machine_id, "is_active": False}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp = client.put("/api/v1/masters/machines", json={"id": machine_id, "is_active": False}, headers=op_headers)
    assert resp.status_code == 403


def test_machine_duplicate_code_rejected(client, test_db):
    admin_headers, _ = _auth(test_db, "admin.mach2@vspl.com", UserRole.ADMIN)
    client.post("/api/v1/masters/machines", json={"machine_code": "M-DUP", "machine_name": "A"}, headers=admin_headers)
    resp = client.post("/api/v1/masters/machines", json={"machine_code": "M-DUP", "machine_name": "B"}, headers=admin_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Shift
# ---------------------------------------------------------------------------

def test_shift_crud_and_rbac(client, test_db):
    admin_headers, _ = _auth(test_db, "admin.shift@vspl.com", UserRole.ADMIN)
    op_headers, _ = _auth(test_db, "op.shift@vspl.com", UserRole.MACHINE_OPERATOR)

    resp = client.post("/api/v1/masters/shifts", json={
        "shift_code": "A", "shift_name": "Shift A", "start_time": "06:00", "end_time": "14:00"
    }, headers=op_headers)
    assert resp.status_code == 403

    resp = client.post("/api/v1/masters/shifts", json={
        "shift_code": "A", "shift_name": "Shift A", "start_time": "06:00", "end_time": "14:00"
    }, headers=admin_headers)
    assert resp.status_code == 200
    shift_id = resp.json()["id"]

    resp = client.put("/api/v1/masters/shifts", json={"id": shift_id, "is_active": False}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

def test_operator_links_existing_user_without_duplicating_identity(client, test_db):
    admin_headers, admin_user = _auth(test_db, "admin.opr@vspl.com", UserRole.ADMIN)
    _, floor_user = _auth(test_db, "floor.opr@vspl.com", UserRole.MACHINE_OPERATOR)

    resp = client.post("/api/v1/masters/operators", json={
        "user_id": str(floor_user.id), "employee_code": "EMP-001", "display_name": floor_user.full_name
    }, headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == str(floor_user.id)
    assert body["employee_code"] == "EMP-001"


def test_operator_rbac_and_duplicate_employee_code_rejected(client, test_db):
    admin_headers, _ = _auth(test_db, "admin.opr2@vspl.com", UserRole.ADMIN)
    op_headers, _ = _auth(test_db, "op.opr2@vspl.com", UserRole.MACHINE_OPERATOR)

    resp = client.post("/api/v1/masters/operators", json={"display_name": "Floor Op 1", "employee_code": "EMP-100"}, headers=op_headers)
    assert resp.status_code == 403

    resp = client.post("/api/v1/masters/operators", json={"display_name": "Floor Op 1", "employee_code": "EMP-100"}, headers=admin_headers)
    assert resp.status_code == 200

    resp = client.post("/api/v1/masters/operators", json={"display_name": "Floor Op 2", "employee_code": "EMP-100"}, headers=admin_headers)
    assert resp.status_code == 400
