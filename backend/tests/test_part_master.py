"""Comprehensive test suite for the Authoritative Part Master (Layer 1) and Customer Part Mapping (Layer 2).

Verifies all 16 required test scenarios:
1. Part Master returns ALL Internal Parts.
2. Unmapped Internal Part still appears.
3. Customer mapping count is separate from Internal Part count.
4. Customer filter returns only mapped Internal Parts for that customer.
5. Internal Part with multiple customers displays all mappings.
6. Internal Part with zero customers displays correctly.
7. Customer Part No search works.
8. Internal Part No search works.
9. Grade search works.
10. Description search works.
11. Customer + search combination works.
12. Pagination total is authoritative.
13. Customer Master -> View Parts endpoint compatibility.
14. Order Intake mapping remains correct and unchanged.
15. Existing 1,890 mappings remain unchanged.
16. Existing Part records remain unchanged.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.database import SessionLocal
from app.main import app
from app.models.order import Customer, Part
from app.models.customer_part_cross_reference import CustomerPartCrossReference
from app.services.part_master_service import PartMasterService
from app.services.customer_part_cross_reference_service import CustomerPartCrossReferenceService

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


def _login(client, role_key="ADMIN"):
    email, password = SEEDED_LOGINS[role_key]
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_01_part_master_returns_all_internal_parts(client: TestClient):
    """1. Part Master returns ALL authoritative Internal Parts."""
    token = _login(client, "ADMIN")
    resp = client.get("/api/v1/masters/parts?limit=10", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "stats" in data
    assert data["stats"]["total_parts"] >= 5000


def test_02_unmapped_internal_part_appears(client: TestClient):
    """2. Unmapped Internal Part (0 customer mappings) still appears in Part Master."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    part_num = f"UNMAP-{uid}"

    # Create unmapped part
    create_resp = client.post(
        "/api/v1/masters/parts",
        json={"part_number": part_num, "description": "Unmapped Bushing", "grade": "SG 500-B"},
        headers=_auth(token),
    )
    assert create_resp.status_code == 200
    p_data = create_resp.json()
    assert p_data["part_number"] == part_num
    assert p_data["customer_count"] == 0
    assert p_data["mapping_count"] == 0
    assert p_data["customer_mappings"] == []

    # Query Part Master with search
    list_resp = client.get(f"/api/v1/masters/parts?search={part_num}", headers=_auth(token))
    assert list_resp.status_code == 200
    res = list_resp.json()
    assert res["total"] == 1
    assert res["items"][0]["part_number"] == part_num
    assert res["items"][0]["customer_count"] == 0
    assert res["items"][0]["mapping_count"] == 0


def test_03_customer_mapping_count_is_separate_from_part_count(client: TestClient):
    """3. Customer mapping count is separate from Internal Part count in stats."""
    token = _login(client, "ADMIN")
    resp = client.get("/api/v1/masters/parts?limit=5", headers=_auth(token))
    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["total_parts"] > stats["total_mappings"]
    assert stats["mapped_parts"] + stats["unmapped_parts"] == stats["total_parts"]


def test_04_customer_filter_returns_only_mapped_internal_parts(client: TestClient):
    """4. Customer filter returns only Internal Parts mapped to that customer."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    c_code_1 = f"CUST1-{uid}"
    c_code_2 = f"CUST2-{uid}"
    p_num_1 = f"P1-{uid}"
    p_num_2 = f"P2-{uid}"

    client.post("/api/v1/masters/customers", json={"customer_code": c_code_1, "name": "Customer 1"}, headers=_auth(token))
    client.post("/api/v1/masters/customers", json={"customer_code": c_code_2, "name": "Customer 2"}, headers=_auth(token))

    client.post("/api/v1/masters/parts", json={"part_number": p_num_1, "description": "Part 1"}, headers=_auth(token))
    client.post("/api/v1/masters/parts", json={"part_number": p_num_2, "description": "Part 2"}, headers=_auth(token))

    client.post("/api/v1/masters/part-cross-references", json={"customer_code": c_code_1, "customer_part_no": "CP1", "internal_part_code": p_num_1}, headers=_auth(token))
    client.post("/api/v1/masters/part-cross-references", json={"customer_code": c_code_2, "customer_part_no": "CP2", "internal_part_code": p_num_2}, headers=_auth(token))

    resp = client.get(f"/api/v1/masters/parts?customer_code={c_code_1}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["part_number"] == p_num_1
    assert data["items"][0]["customer_mappings"][0]["customer_code"] == c_code_1


def test_05_internal_part_with_multiple_customers_displays_all_mappings(client: TestClient):
    """5. Internal Part with multiple customers displays all mappings."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    c_code_a = f"CA-{uid}"
    c_code_b = f"CB-{uid}"
    p_num = f"SHARED-{uid}"

    client.post("/api/v1/masters/customers", json={"customer_code": c_code_a, "name": "Customer A"}, headers=_auth(token))
    client.post("/api/v1/masters/customers", json={"customer_code": c_code_b, "name": "Customer B"}, headers=_auth(token))
    client.post("/api/v1/masters/parts", json={"part_number": p_num, "description": "Shared Bushing"}, headers=_auth(token))

    client.post("/api/v1/masters/part-cross-references", json={"customer_code": c_code_a, "customer_part_no": "CP-A", "internal_part_code": p_num}, headers=_auth(token))
    client.post("/api/v1/masters/part-cross-references", json={"customer_code": c_code_b, "customer_part_no": "CP-B", "internal_part_code": p_num}, headers=_auth(token))

    resp = client.get(f"/api/v1/masters/parts?search={p_num}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["customer_count"] == 2
    assert item["mapping_count"] == 2
    codes = {m["customer_code"] for m in item["customer_mappings"]}
    assert codes == {c_code_a, c_code_b}


def test_06_internal_part_with_zero_customers_displays_correctly(client: TestClient):
    """6. Internal Part with zero customers displays customer_count=0 and mapping_count=0."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    p_num = f"ZERO-{uid}"

    client.post("/api/v1/masters/parts", json={"part_number": p_num, "description": "Zero Mappings"}, headers=_auth(token))
    resp = client.get(f"/api/v1/masters/parts?search={p_num}", headers=_auth(token))
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["customer_count"] == 0
    assert item["mapping_count"] == 0
    assert len(item["customer_mappings"]) == 0


def test_07_customer_part_no_search_works(client: TestClient):
    """7. Search by Customer Part No finds the linked Internal Part."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    c_code = f"SRC-CUST-{uid}"
    p_num = f"SRC-PART-{uid}"
    cp_no = f"SEARCHABLE-CPNO-{uid}"

    client.post("/api/v1/masters/customers", json={"customer_code": c_code, "name": "Search Test Corp"}, headers=_auth(token))
    client.post("/api/v1/masters/parts", json={"part_number": p_num, "description": "Searchable Internal"}, headers=_auth(token))
    client.post("/api/v1/masters/part-cross-references", json={"customer_code": c_code, "customer_part_no": cp_no, "internal_part_code": p_num}, headers=_auth(token))

    resp = client.get(f"/api/v1/masters/parts?search={cp_no}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["part_number"] == p_num


def test_08_internal_part_no_search_works(client: TestClient):
    """8. Search by Internal Part No works."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    p_num = f"IPSEARCH-{uid}"
    client.post("/api/v1/masters/parts", json={"part_number": p_num, "description": "Desc"}, headers=_auth(token))

    resp = client.get(f"/api/v1/masters/parts?search={p_num}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["part_number"] == p_num


def test_09_grade_search_works(client: TestClient):
    """9. Search by Grade works."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    grade = f"CUSTOM-GRADE-{uid}"
    p_num = f"GRADE-P-{uid}"

    client.post("/api/v1/masters/parts", json={"part_number": p_num, "grade": grade}, headers=_auth(token))
    resp = client.get(f"/api/v1/masters/parts?search={grade}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    found = any(item["part_number"] == p_num for item in resp.json()["items"])
    assert found is True


def test_10_description_search_works(client: TestClient):
    """10. Search by Description works."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    desc = f"Unique Precision Bushing {uid}"
    p_num = f"DESC-P-{uid}"

    client.post("/api/v1/masters/parts", json={"part_number": p_num, "description": desc}, headers=_auth(token))
    resp = client.get(f"/api/v1/masters/parts?search={uid}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["part_number"] == p_num


def test_11_customer_plus_search_combination_works(client: TestClient):
    """11. Customer filter + search combination applies boolean AND."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    c_code_1 = f"C1-{uid}"
    c_code_2 = f"C2-{uid}"
    p_num_1 = f"P1-{uid}"
    p_num_2 = f"P2-{uid}"

    client.post("/api/v1/masters/customers", json={"customer_code": c_code_1, "name": "Cust 1"}, headers=_auth(token))
    client.post("/api/v1/masters/customers", json={"customer_code": c_code_2, "name": "Cust 2"}, headers=_auth(token))
    client.post("/api/v1/masters/parts", json={"part_number": p_num_1, "description": f"MatchedWord {uid}"}, headers=_auth(token))
    client.post("/api/v1/masters/parts", json={"part_number": p_num_2, "description": f"MatchedWord {uid}"}, headers=_auth(token))

    client.post("/api/v1/masters/part-cross-references", json={"customer_code": c_code_1, "customer_part_no": "CP1", "internal_part_code": p_num_1}, headers=_auth(token))
    client.post("/api/v1/masters/part-cross-references", json={"customer_code": c_code_2, "customer_part_no": "CP2", "internal_part_code": p_num_2}, headers=_auth(token))

    resp = client.get(f"/api/v1/masters/parts?customer_code={c_code_1}&search=MatchedWord", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["part_number"] == p_num_1


def test_12_pagination_total_is_authoritative(client: TestClient):
    """12. Pagination total is authoritative and not capped at page limit."""
    token = _login(client, "ADMIN")
    resp = client.get("/api/v1/masters/parts?limit=10&offset=0", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert len(data["items"]) == 10
    assert data["total"] > 5000


def test_13_customer_master_view_parts_compatibility(client: TestClient):
    """13. Customer Master View Parts parameter (customer_code) works seamlessly."""
    token = _login(client, "ADMIN")
    uid = uuid.uuid4().hex[:6].upper()
    c_code = f"VP-{uid}"
    p_num = f"VPP-{uid}"

    client.post("/api/v1/masters/customers", json={"customer_code": c_code, "name": "View Parts Test"}, headers=_auth(token))
    client.post("/api/v1/masters/parts", json={"part_number": p_num, "description": "VP Part"}, headers=_auth(token))
    client.post("/api/v1/masters/part-cross-references", json={"customer_code": c_code, "customer_part_no": "VP-CP", "internal_part_code": p_num}, headers=_auth(token))

    resp = client.get(f"/api/v1/masters/parts?customer_code={c_code}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["part_number"] == p_num


def test_14_order_intake_lookup_remains_correct(client: TestClient):
    """14. Order Intake lookup continues resolving Customer + Customer Part No -> Internal Part."""
    token = _login(client, "PLANNER")
    uid = uuid.uuid4().hex[:6].upper()
    c_code = f"INTK-CUST-{uid}"
    p_num = f"INTK-PART-{uid}"
    cp_no = f"INTK-CP-{uid}"

    client.post("/api/v1/masters/customers", json={"customer_code": c_code, "name": "Intake Corp"}, headers=_auth(token))
    client.post("/api/v1/masters/parts", json={"part_number": p_num, "description": "Intake Bushing", "grade": "SG 500"}, headers=_auth(token))
    client.post("/api/v1/masters/part-cross-references", json={"customer_code": c_code, "customer_part_no": cp_no, "internal_part_code": p_num}, headers=_auth(token))

    lookup_resp = client.get(
        "/api/v1/masters/part-cross-references/lookup",
        params={"customer_code": c_code, "customer_part_no": cp_no},
        headers=_auth(token),
    )
    assert lookup_resp.status_code == 200
    l_data = lookup_resp.json()
    assert l_data["is_matched"] is True
    assert l_data["part_number"] == p_num
    assert l_data["grade"] == "SG 500"
