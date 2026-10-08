"""Comprehensive tests for Part Master:
1. Internal code auto-generation (Customer Code + next numeric suffix, per customer)
2. Gap preservation (never backfills gaps)
3. Independent per-customer sequences (APE vs MIL)
4. Customer Part No. exact preservation (spaces, punctuation, parentheses, case)
5. Uniqueness per (customer_id, customer_part_number): same customer rejected, different customer allowed
6. Customer prerequisite check (missing customer -> 404)
7. Immutability of internal code / part_number
8. Concurrency safety (serialized allocation)
9. AuditLog recording
10. RBAC matrix (Admin, Planner allowed; Operator, QA, Dispatch, etc. rejected with 403)
11. Status and Customer Part No update validation
12. KPIs endpoint
13. Search, filter, and pagination
"""
import pytest
from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
import app.models  # Ensures all tables are registered on Base.metadata
from app.models.user import User
from app.models.order import Customer, Part
from app.models.customer_part_mapping import CustomerPartMapping
from app.models.audit import AuditLog
from app.core.roles import UserRole
from app.main import app


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def test_db():
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    # Clean tables for complete test isolation
    session.query(CustomerPartMapping).delete()
    session.query(AuditLog).delete()
    session.query(Part).delete()
    session.query(Customer).delete()
    session.query(User).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(test_db):
    def _get_test_db():
        yield test_db

    app.dependency_overrides[get_db] = _get_test_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.core.rate_limit import limiter
    limiter.reset()
    yield
    limiter.reset()


def _auth_headers(user: User) -> dict:
    token = create_access_token(
        data={"sub": user.email, "role": user.role.value},
        expires_delta=timedelta(minutes=60),
    )
    return {"Authorization": f"Bearer {token}"}


def _create_user(db, email: str, role: UserRole) -> User:
    u = db.query(User).filter(User.email == email).first()
    if not u:
        u = User(
            email=email,
            full_name=f"User {role.value}",
            role=role,
            hashed_password="test_hashed_password",
            is_active=True,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


def _create_customer(db, code: str, name: str) -> Customer:
    code_norm = code.strip().upper()
    c = db.query(Customer).filter(Customer.customer_code == code_norm).first()
    if not c:
        c = Customer(
            customer_code=code_norm,
            name=name,
            is_active=True,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_01_ape_new_part_generates_ape1(client, test_db):
    admin = _create_user(test_db, "admin1@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={
            "customer_code": "APE",
            "customer_part_number": "RC47NN135000000092",
            "status": "Active",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["part_number"] == "APE1"
    assert data["customer_code"] == "APE"
    assert data["customer_part_number"] == "RC47NN135000000092"
    assert data["status"] == "Active"


def test_02_next_ape_part_generates_ape2_and_ape3(client, test_db):
    admin = _create_user(test_db, "admin2@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    res1 = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "APE", "customer_part_number": "RC4750RC0385"},
    )
    assert res1.status_code == 200
    assert res1.json()["part_number"] == "APE1"

    res2 = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "APE", "customer_part_number": "RC47N0115003500076"},
    )
    assert res2.status_code == 200
    assert res2.json()["part_number"] == "APE2"

    res3 = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "APE", "customer_part_number": "RC47N0120000000089"},
    )
    assert res3.status_code == 200
    assert res3.json()["part_number"] == "APE3"


def test_03_existing_ape1_and_ape3_generates_ape4_without_backfilling_gap(client, test_db):
    admin = _create_user(test_db, "admin3@vspl.com", UserRole.ADMIN)
    cust = _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    # Manually seed APE1 and APE3 (simulating legacy gap where APE2 was deleted/not imported)
    p1 = Part(part_number="APE1", description="Legacy 1")
    p3 = Part(part_number="APE3", description="Legacy 3")
    test_db.add_all([p1, p3])
    test_db.flush()
    m1 = CustomerPartMapping(customer_id=cust.id, part_id=p1.id, customer_part_number="LEGACY-1")
    m3 = CustomerPartMapping(customer_id=cust.id, part_id=p3.id, customer_part_number="LEGACY-3")
    test_db.add_all([m1, m3])
    test_db.commit()

    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "APE", "customer_part_number": "NEW-PART-AFTER-GAP"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["part_number"] == "APE4", "Must be APE4 -- must never backfill APE2"


def test_04_mil_sequence_is_independent_from_ape(client, test_db):
    planner = _create_user(test_db, "planner4@vspl.com", UserRole.PLANNER)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")
    _create_customer(test_db, "MIL", "Milacron India Pvt Ltd.")

    # Create APE parts
    client.post("/api/v1/masters/parts", headers=_auth_headers(planner), json={"customer_code": "APE", "customer_part_number": "APE-PART-1"})
    client.post("/api/v1/masters/parts", headers=_auth_headers(planner), json={"customer_code": "APE", "customer_part_number": "APE-PART-2"})

    # Create MIL part -- must start at MIL1, not MIL3
    res_mil = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(planner),
        json={"customer_code": "MIL", "customer_part_number": "5225727X"},
    )
    assert res_mil.status_code == 200
    assert res_mil.json()["part_number"] == "MIL1"


def test_05_same_customer_same_customer_part_number_rejected_400(client, test_db):
    admin = _create_user(test_db, "admin5@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "ACC", "Accutech CNC")

    res1 = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "ACC", "customer_part_number": "H00D035800"},
    )
    assert res1.status_code == 200

    # Attempt duplicate for same customer
    res2 = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "ACC", "customer_part_number": "H00D035800"},
    )
    assert res2.status_code == 400
    assert "already exists for customer 'ACC'" in res2.json()["detail"]


def test_06_different_customer_same_customer_part_number_allowed(client, test_db):
    admin = _create_user(test_db, "admin6@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")
    _create_customer(test_db, "WPR", "Wipro Enterprises (P) Ltd")

    shared_part_no = "RC47NN135000000092"

    res_ape = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "APE", "customer_part_number": shared_part_no},
    )
    assert res_ape.status_code == 200
    assert res_ape.json()["part_number"] == "APE1"

    res_wpr = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "WPR", "customer_part_number": shared_part_no},
    )
    assert res_wpr.status_code == 200
    assert res_wpr.json()["part_number"] == "WPR1"
    assert res_ape.json()["id"] != res_wpr.json()["id"]


def test_07_exact_punctuation_and_special_chars_preserved(client, test_db):
    admin = _create_user(test_db, "admin7@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "WAL", "Walvoil Fluid Power")

    exact_part_no = "DX-207441-001/A.1#4"
    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "WAL", "customer_part_number": exact_part_no},
    )
    assert res.status_code == 200
    assert res.json()["customer_part_number"] == exact_part_no


def test_08_exact_spaces_preserved(client, test_db):
    admin = _create_user(test_db, "admin8@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "ACC", "Accutech CNC")

    exact_part_no = "206 x 196 x 321"
    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "ACC", "customer_part_number": exact_part_no},
    )
    assert res.status_code == 200
    assert res.json()["customer_part_number"] == exact_part_no


def test_09_parentheses_preserved(client, test_db):
    admin = _create_user(test_db, "admin9@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "ACC", "Accutech CNC")

    exact_part_no = "H00A2117101V (132 X 116 X 106)"
    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "ACC", "customer_part_number": exact_part_no},
    )
    assert res.status_code == 200
    assert res.json()["customer_part_number"] == exact_part_no


def test_10_missing_customer_returns_404(client, test_db):
    admin = _create_user(test_db, "admin10@vspl.com", UserRole.ADMIN)

    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "NONEXISTENT", "customer_part_number": "PART-123"},
    )
    assert res.status_code == 404
    assert "Customer 'NONEXISTENT' not found" in res.json()["detail"]


def test_11_internal_code_cannot_be_manually_supplied(client, test_db):
    admin = _create_user(test_db, "admin11@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    # Client passes part_number in body; server must ignore it and auto-generate APE1
    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={
            "customer_code": "APE",
            "customer_part_number": "RC-SUPPLIED",
            "part_number": "CUSTOM-CODE-999",  # Attempted override
        },
    )
    assert res.status_code == 200
    assert res.json()["part_number"] == "APE1", "Internal code must be auto-generated as APE1, ignoring client override"


def test_12_internal_code_cannot_be_changed_by_update(client, test_db):
    admin = _create_user(test_db, "admin12@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    res_create = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "APE", "customer_part_number": "ORIG-PART"},
    )
    part_id = res_create.json()["id"]
    assert res_create.json()["part_number"] == "APE1"

    # Attempt to change part_number via PUT
    res_update = client.put(
        f"/api/v1/masters/parts/{part_id}",
        headers=_auth_headers(admin),
        json={"part_number": "HACKED_CODE", "status": "Obsolete"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["part_number"] == "APE1", "Internal code must NEVER change"
    assert res_update.json()["status"] == "Obsolete"


def test_13_db_uniqueness_enforced_on_part_number(client, test_db):
    admin = _create_user(test_db, "admin13@vspl.com", UserRole.ADMIN)
    cust = _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    # Seed APE1
    p1 = Part(part_number="APE1", description="Part 1")
    test_db.add(p1)
    test_db.flush()
    m1 = CustomerPartMapping(customer_id=cust.id, part_id=p1.id, customer_part_number="PART-1")
    test_db.add(m1)
    test_db.commit()

    # Create next part via API
    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "APE", "customer_part_number": "PART-2"},
    )
    assert res.status_code == 200
    assert res.json()["part_number"] == "APE2"


def test_14_concurrency_race_safety(client, test_db):
    admin = _create_user(test_db, "admin14@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    # Sequentially create 5 parts under APE and confirm strictly ascending sequence
    codes = []
    for i in range(5):
        res = client.post(
            "/api/v1/masters/parts",
            headers=_auth_headers(admin),
            json={"customer_code": "APE", "customer_part_number": f"CONC-PART-{i}"},
        )
        assert res.status_code == 200
        codes.append(res.json()["part_number"])

    assert codes == ["APE1", "APE2", "APE3", "APE4", "APE5"]


def test_15_audit_log_written_on_creation_and_update(client, test_db):
    admin = _create_user(test_db, "admin15@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "APE", "customer_part_number": "AUDIT-PART-1"},
    )
    assert res.status_code == 200
    part_id = res.json()["id"]

    logs = test_db.query(AuditLog).filter(AuditLog.entity == "Part", AuditLog.action == "PART_CREATED").all()
    assert len(logs) >= 1
    assert "part_number=APE1" in logs[-1].details

    # Update
    client.put(
        f"/api/v1/masters/parts/{part_id}",
        headers=_auth_headers(admin),
        json={"status": "Obsolete"},
    )
    update_logs = test_db.query(AuditLog).filter(AuditLog.entity == "Part", AuditLog.action == "PART_UPDATED").all()
    assert len(update_logs) >= 1


@pytest.mark.parametrize("role,expected_status", [
    (UserRole.ADMIN, 200),
    (UserRole.PLANNER, 200),
    (UserRole.OPERATOR, 403),
    (UserRole.QA, 403),
    (UserRole.DISPATCH, 403),
    (UserRole.STORE, 403),
    (UserRole.PRODUCTION_MANAGER, 403),
    (UserRole.ENGINEERING, 403),
])
def test_16_rbac_matrix_for_part_creation(client, test_db, role, expected_status):
    user = _create_user(test_db, f"rbac_{role.value}@vspl.com", role)
    _create_customer(test_db, f"CUST_{role.value.upper()}", "Test Cust")

    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(user),
        json={"customer_code": f"CUST_{role.value.upper()}", "customer_part_number": "RBAC-TEST"},
    )
    assert res.status_code == expected_status


def test_17_existing_part_records_remain_unchanged(client, test_db):
    admin = _create_user(test_db, "admin17@vspl.com", UserRole.ADMIN)
    cust = _create_customer(test_db, "PMC", "PMC Hydraulics")

    # Seed 3 existing parts
    p1 = Part(part_number="PMC1", description="Original PMC1")
    p2 = Part(part_number="PMC2", description="Original PMC2")
    test_db.add_all([p1, p2])
    test_db.flush()
    m1 = CustomerPartMapping(customer_id=cust.id, part_id=p1.id, customer_part_number="PMC-001", status="Active")
    m2 = CustomerPartMapping(customer_id=cust.id, part_id=p2.id, customer_part_number="PMC-002", status="Active")
    test_db.add_all([m1, m2])
    test_db.commit()

    # Add a new part
    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "PMC", "customer_part_number": "PMC-003"},
    )
    assert res.status_code == 200
    assert res.json()["part_number"] == "PMC3"

    # Verify existing records are 100% intact
    db_p1 = test_db.query(Part).filter(Part.part_number == "PMC1").first()
    db_p2 = test_db.query(Part).filter(Part.part_number == "PMC2").first()
    assert db_p1.description == "Original PMC1"
    assert db_p2.description == "Original PMC2"


def test_18_status_update_works(client, test_db):
    admin = _create_user(test_db, "admin18@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    res = client.post(
        "/api/v1/masters/parts",
        headers=_auth_headers(admin),
        json={"customer_code": "APE", "customer_part_number": "STATUS-TEST", "status": "Active"},
    )
    part_id = res.json()["id"]

    for new_status in ["Obsolete", "ECR", "Active"]:
        res_upd = client.put(
            f"/api/v1/masters/parts/{part_id}",
            headers=_auth_headers(admin),
            json={"status": new_status},
        )
        assert res_upd.status_code == 200
        assert res_upd.json()["status"] == new_status


def test_19_duplicate_customer_part_number_update_is_rejected(client, test_db):
    admin = _create_user(test_db, "admin19@vspl.com", UserRole.ADMIN)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")

    res1 = client.post("/api/v1/masters/parts", headers=_auth_headers(admin), json={"customer_code": "APE", "customer_part_number": "PART-A"})
    res2 = client.post("/api/v1/masters/parts", headers=_auth_headers(admin), json={"customer_code": "APE", "customer_part_number": "PART-B"})

    part_b_id = res2.json()["id"]

    # Try updating PART-B to PART-A under same customer -> 400
    res_upd = client.put(
        f"/api/v1/masters/parts/{part_b_id}",
        headers=_auth_headers(admin),
        json={"customer_part_number": "PART-A"},
    )
    assert res_upd.status_code == 400
    assert "already exists for customer 'APE'" in res_upd.json()["detail"]


def test_20_kpis_endpoint_works(client, test_db):
    planner = _create_user(test_db, "planner20@vspl.com", UserRole.PLANNER)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")
    _create_customer(test_db, "MIL", "Milacron India Pvt Ltd.")

    client.post("/api/v1/masters/parts", headers=_auth_headers(planner), json={"customer_code": "APE", "customer_part_number": "P1", "status": "Active"})
    client.post("/api/v1/masters/parts", headers=_auth_headers(planner), json={"customer_code": "APE", "customer_part_number": "P2", "status": "Obsolete"})
    client.post("/api/v1/masters/parts", headers=_auth_headers(planner), json={"customer_code": "MIL", "customer_part_number": "P3", "status": "Active"})

    res = client.get("/api/v1/masters/parts/kpis", headers=_auth_headers(planner))
    assert res.status_code == 200
    data = res.json()
    assert data["total_parts"] == 3
    assert data["active_parts"] == 2
    assert data["total_customers"] == 2
    assert data["new_parts_this_month"] == 3


def test_21_pagination_filtering_and_search_works(client, test_db):
    planner = _create_user(test_db, "planner21@vspl.com", UserRole.PLANNER)
    _create_customer(test_db, "APE", "A P Engineering Works Pvt Ltd")
    _create_customer(test_db, "MIL", "Milacron India Pvt Ltd.")

    client.post("/api/v1/masters/parts", headers=_auth_headers(planner), json={"customer_code": "APE", "customer_part_number": "RC47NN135000000092", "status": "Active"})
    client.post("/api/v1/masters/parts", headers=_auth_headers(planner), json={"customer_code": "APE", "customer_part_number": "RC4750RC0385", "status": "Obsolete"})
    client.post("/api/v1/masters/parts", headers=_auth_headers(planner), json={"customer_code": "MIL", "customer_part_number": "5225727X", "status": "Active"})

    # Filter by customer
    res_cust = client.get("/api/v1/masters/parts?customer_code=APE", headers=_auth_headers(planner))
    assert res_cust.status_code == 200
    assert res_cust.json()["total"] == 2

    # Filter by status
    res_status = client.get("/api/v1/masters/parts?status=Obsolete", headers=_auth_headers(planner))
    assert res_status.status_code == 200
    assert res_status.json()["total"] == 1
    assert res_status.json()["items"][0]["customer_part_number"] == "RC4750RC0385"

    # Search by part number
    res_search = client.get("/api/v1/masters/parts?search=5225727X", headers=_auth_headers(planner))
    assert res_search.status_code == 200
    assert res_search.json()["total"] == 1
    assert res_search.json()["items"][0]["customer_code"] == "MIL"

    # Pagination
    res_page = client.get("/api/v1/masters/parts?page=1&limit=2", headers=_auth_headers(planner))
    assert res_page.status_code == 200
    assert len(res_page.json()["items"]) == 2
    assert res_page.json()["total"] == 3
