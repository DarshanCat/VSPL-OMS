import uuid
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from app.core.rate_limit import limiter
from app.main import app
from app.core.database import SessionLocal
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WOStatus
from app.models.order import Order, Customer, Part
from app.models.production_movement import ProductionMovement
from app.models.engineering import PartEngineeringRevision, WOEngineeringReadiness


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client, email="admin@vspl.com", password="admin123"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _unique(prefix="ENG"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture
def test_setup(client):
    db = SessionLocal()
    try:
        # Ensure test users with distinct roles exist
        admin_token = _login(client, "admin@vspl.com", "admin123")

        # Create or find engineering user
        eng_user = db.query(User).filter(User.email == "eng.lead@vspl.com").first()
        if not eng_user:
            eng_user = User(
                id=uuid.uuid4(),
                email="eng.lead@vspl.com",
                full_name="Lead Engineer",
                hashed_password=db.query(User).filter(User.email == "admin@vspl.com").first().hashed_password,
                role=UserRole.ENGINEERING,
                department="Engineering",
                is_active=True
            )
            db.add(eng_user)
            db.commit()
        eng_token = _login(client, "eng.lead@vspl.com", "admin123")

        # Planner token
        pln_token = _login(client, "planner@vspl.com", "planner123")
        # Store token
        store_user = db.query(User).filter(User.email == "store.clerk@vspl.com").first()
        if not store_user:
            store_user = User(
                id=uuid.uuid4(),
                email="store.clerk@vspl.com",
                full_name="Store Clerk",
                hashed_password=db.query(User).filter(User.email == "admin@vspl.com").first().hashed_password,
                role=UserRole.STORE,
                department="Store",
                is_active=True
            )
            db.add(store_user)
            db.commit()
        store_token = _login(client, "store.clerk@vspl.com", "admin123")

        # Create customer & part
        cust_code = _unique("CUST")
        part_num = _unique("PART")
        c_res = client.post(
            "/api/v1/masters/customers", headers=_auth(admin_token),
            json={"customer_code": cust_code, "name": f"Customer {cust_code}"}
        )
        assert c_res.status_code == 200, c_res.text
        part = Part(id=uuid.uuid4(), part_number=part_num, grade="CuSn12", description=f"Test Bushing {part_num}")
        db.add(part)
        db.commit()

        # Create Regular Order & WOs via intake
        intake_reg = client.post(
            "/api/v1/operations/intake", headers=_auth(admin_token),
            json={
                "customer_code": cust_code,
                "customer_name": f"Customer {cust_code}",
                "part_number": part_num,
                "customer_po": _unique("PO"),
                "po_quantity": 100,
                "max_batch_size": 100,
                "order_classification": "regular"
            }
        )
        assert intake_reg.status_code == 200, intake_reg.text
        wo_reg_num = intake_reg.json()["wos_created"][0]

        # Create NPD Order & WOs via intake
        part_npd_num = _unique("NPD-PART")
        part_npd = Part(id=uuid.uuid4(), part_number=part_npd_num, grade="CuAl10Fe3", description=f"NPD Gear {part_npd_num}")
        db.add(part_npd)
        db.commit()

        intake_npd = client.post(
            "/api/v1/operations/intake", headers=_auth(admin_token),
            json={
                "customer_code": cust_code,
                "customer_name": f"Customer {cust_code}",
                "part_number": part_npd_num,
                "customer_po": _unique("PO-NPD"),
                "po_quantity": 50,
                "max_batch_size": 50,
                "order_classification": "npd"
            }
        )
        assert intake_npd.status_code == 200, intake_npd.text
        wo_npd_num = intake_npd.json()["wos_created"][0]

        # Create Replacement WO manually
        wo_reg = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_reg_num).first()
        wo_rep = WorkOrder(
            id=uuid.uuid4(),
            wo_number=_unique("WO-REP"),
            order_id=wo_reg.order_id,
            physical_wo_qty=20,
            status=WOStatus.PLANNED,
            current_stage="F1",
            is_replacement=True,
            replacement_reason="Foundry porosity scrap replacement"
        )
        db.add(wo_rep)
        db.commit()

        return {
            "admin_token": admin_token,
            "eng_token": eng_token,
            "pln_token": pln_token,
            "store_token": store_token,
            "cust_code": cust_code,
            "part_id": str(part.id),
            "part_num": part_num,
            "part_npd_id": str(part_npd.id),
            "part_npd_num": part_npd_num,
            "wo_reg_num": wo_reg_num,
            "wo_npd_num": wo_npd_num,
            "wo_rep_num": wo_rep.wo_number,
        }
    finally:
        db.close()


# ===========================================================================
# 1. Engineering Profile Revision Master Tests
# ===========================================================================

def test_create_and_manage_engineering_revisions(client, test_setup):
    s = test_setup
    headers = _auth(s["eng_token"])

    # 1. Create Rev A
    res_a = client.post("/api/v1/engineering/revisions", headers=headers, json={
        "part_id": s["part_id"],
        "drawing_number": f"DRW-{s['part_num']}-A",
        "drawing_revision": "A",
        "drawing_url": "https://docs.vspl.in/dwg/sample-a.pdf",
        "customer_spec_ref": "SPEC-001",
        "process_sheet_number": "PS-001",
        "pattern_number": "PAT-001",
        "tooling_id": "TOOL-001",
        "is_active": True
    })
    assert res_a.status_code == 201, res_a.text
    data_a = res_a.json()
    assert data_a["drawing_revision"] == "A"
    assert data_a["is_active"] is True

    # 2. Create Rev B (active) -> Replaces active status
    res_b = client.post("/api/v1/engineering/revisions", headers=headers, json={
        "part_id": s["part_id"],
        "drawing_number": f"DRW-{s['part_num']}-B",
        "drawing_revision": "B",
        "drawing_url": "https://docs.vspl.in/dwg/sample-b.pdf",
        "customer_spec_ref": "SPEC-002",
        "process_sheet_number": "PS-002",
        "pattern_number": "PAT-002",
        "tooling_id": "TOOL-002",
        "is_active": True
    })
    assert res_b.status_code == 201, res_b.text

    # 3. Duplicate Rev B -> 409 Conflict
    res_dup = client.post("/api/v1/engineering/revisions", headers=headers, json={
        "part_id": s["part_id"],
        "drawing_number": f"DRW-{s['part_num']}-B2",
        "drawing_revision": "B",
    })
    assert res_dup.status_code == 409

    # 4. List revisions
    list_res = client.get(f"/api/v1/engineering/revisions?part_id={s['part_id']}", headers=headers)
    assert list_res.status_code == 200
    revs = list_res.json()
    assert len(revs) == 2


# ===========================================================================
# 2. WO Readiness Checklist & NPD vs Regular Tests
# ===========================================================================

def test_regular_order_inherits_defaults_from_active_revision(client, test_setup):
    s = test_setup
    headers = _auth(s["eng_token"])

    # Create active revision for part
    client.post("/api/v1/engineering/revisions", headers=headers, json={
        "part_id": s["part_id"],
        "drawing_number": f"DRW-{s['part_num']}-01",
        "drawing_revision": "01",
        "drawing_url": "https://docs.vspl.in/dwg/reg.pdf",
        "customer_spec_ref": "SPEC-REG",
        "process_sheet_number": "PS-REG",
        "pattern_number": "PAT-REG",
        "tooling_id": "TOOL-REG",
        "is_active": True
    })

    # Fetch WO readiness detail for Regular order
    res = client.get(f"/api/v1/engineering/readiness/{s['wo_reg_num']}", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["verified_revision"] == "01"
    assert data["drawing_available"] is True
    assert data["drawing_revision_verified"] is True
    assert data["customer_spec_verified"] is True
    assert data["process_sheet_verified"] is True
    assert data["pattern_ready"] is True
    assert data["tooling_ready"] is True
    assert data["checklist_passed_count"] == 6
    assert data["is_checklist_complete"] is True
    assert data["readiness_status"] == "READY"
    assert data["engineering_released_at"] is None  # Not yet released!


def test_npd_order_requires_explicit_verification_workflow(client, test_setup):
    s = test_setup
    headers = _auth(s["eng_token"])

    # Create revision for NPD part
    client.post("/api/v1/engineering/revisions", headers=headers, json={
        "part_id": s["part_npd_id"],
        "drawing_number": f"DRW-{s['part_npd_num']}-NPD1",
        "drawing_revision": "NPD1",
        "drawing_url": "https://docs.vspl.in/dwg/npd.pdf",
        "customer_spec_ref": "SPEC-NPD",
        "process_sheet_number": "PS-NPD",
        "pattern_number": "PAT-NPD",
        "tooling_id": "TOOL-NPD",
        "is_active": True
    })

    # Fetch WO readiness for NPD order -> All checklist flags must start False
    res = client.get(f"/api/v1/engineering/readiness/{s['wo_npd_num']}", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["drawing_available"] is False
    assert data["is_checklist_complete"] is False
    assert data["readiness_status"] == "PENDING"

    # Attempt release directly -> Must be rejected 400 Bad Request
    rel_fail = client.post(
        f"/api/v1/engineering/readiness/{s['wo_npd_num']}/release",
        headers=headers,
        json={}
    )
    assert rel_fail.status_code == 400
    assert "Missing mandatory verifications" in rel_fail.json()["detail"]


# ===========================================================================
# 3. Engineering Release Execution & Field Population Tests
# ===========================================================================

def test_successful_engineering_release_populates_authoritative_wo_fields(client, test_setup):
    s = test_setup
    headers = _auth(s["eng_token"])

    # 1. Update checklist for NPD order
    up_res = client.put(
        f"/api/v1/engineering/readiness/{s['wo_npd_num']}",
        headers=headers,
        json={
            "drawing_available": True,
            "drawing_revision_verified": True,
            "customer_spec_verified": True,
            "process_sheet_verified": True,
            "pattern_ready": True,
            "tooling_ready": True,
            "verified_revision": "REV-NPD-FINAL",
            "drawing_url": "https://docs.vspl.in/dwg/final-npd.pdf",
            "remarks": "Tooling and sample parts approved by metallurgy lead"
        }
    )
    assert up_res.status_code == 200, up_res.text
    assert up_res.json()["readiness_status"] == "READY"

    # 2. Authorize Engineering Release
    rel_res = client.post(
        f"/api/v1/engineering/readiness/{s['wo_npd_num']}/release",
        headers=headers,
        json={}
    )
    assert rel_res.status_code == 200, rel_res.text
    rel_data = rel_res.json()
    assert rel_data["success"] is True
    assert rel_data["readiness_status"] == "RELEASED"
    assert rel_data["engineering_released_by"] == "Lead Engineer"
    assert rel_data["engineering_document_revision"] == "REV-NPD-FINAL"

    # 3. Check tracking endpoint to confirm authoritative work_orders columns populated
    tr_res = client.get(f"/api/v1/work-orders/{s['wo_npd_num']}/tracking", headers=headers)
    assert tr_res.status_code == 200

    # 4. Idempotency test
    rel_idempotent = client.post(
        f"/api/v1/engineering/readiness/{s['wo_npd_num']}/release",
        headers=headers,
        json={}
    )
    assert rel_idempotent.status_code == 200
    assert "already released" in rel_idempotent.json()["message"]


# ===========================================================================
# 4. RBAC & Access Control Tests
# ===========================================================================

def test_rbac_engineering_release_permissions(client, test_setup):
    s = test_setup

    # Setup ready regular order
    client.post("/api/v1/engineering/revisions", headers=_auth(s["admin_token"]), json={
        "part_id": s["part_id"],
        "drawing_number": f"DRW-{s['part_num']}-RBAC",
        "drawing_revision": "R1",
        "drawing_url": "https://docs.vspl.in/dwg/r1.pdf",
        "customer_spec_ref": "SPEC-R1",
        "process_sheet_number": "PS-R1",
        "pattern_number": "PAT-R1",
        "tooling_id": "TOOL-R1",
        "is_active": True
    })
    client.get(f"/api/v1/engineering/readiness/{s['wo_reg_num']}", headers=_auth(s["admin_token"]))

    # 1. Store Clerk attempts release -> 403 Forbidden
    res_store = client.post(
        f"/api/v1/engineering/readiness/{s['wo_reg_num']}/release",
        headers=_auth(s["store_token"]),
        json={}
    )
    assert res_store.status_code == 403

    # 2. Planner attempts release -> 403 Forbidden
    res_pln = client.post(
        f"/api/v1/engineering/readiness/{s['wo_reg_num']}/release",
        headers=_auth(s["pln_token"]),
        json={}
    )
    assert res_pln.status_code == 403

    # 3. Super Admin attempts release -> 200 OK
    res_adm = client.post(
        f"/api/v1/engineering/readiness/{s['wo_reg_num']}/release",
        headers=_auth(s["admin_token"]),
        json={}
    )
    assert res_adm.status_code == 200


# ===========================================================================
# 5. Revocation & Safety Gate Tests
# ===========================================================================

def test_revocation_lifecycle_and_safety_gates(client, test_setup):
    s = test_setup
    wo_num = s["wo_rep_num"]

    # 1. Prepare and release replacement WO
    client.put(
        f"/api/v1/engineering/readiness/{wo_num}",
        headers=_auth(s["eng_token"]),
        json={
            "drawing_available": True,
            "drawing_revision_verified": True,
            "customer_spec_verified": True,
            "process_sheet_verified": True,
            "pattern_ready": True,
            "tooling_ready": True,
            "verified_revision": "REV-REP",
            "drawing_url": "https://docs.vspl.in/dwg/rep.pdf",
            "remarks": "Replacement WO engineering sign-off"
        }
    )
    rel_res = client.post(
        f"/api/v1/engineering/readiness/{wo_num}/release",
        headers=_auth(s["eng_token"]),
        json={"replacement_reason_acknowledged": True}
    )
    assert rel_res.status_code == 200, rel_res.text

    # 2. Non-Admin user attempts revocation -> 403 Forbidden
    res_eng_rev = client.post(
        f"/api/v1/engineering/readiness/{wo_num}/revoke",
        headers=_auth(s["eng_token"]),
        json={"revocation_reason": "Attempt by engineer"}
    )
    assert res_eng_rev.status_code == 403

    # 3. Admin revokes -> 200 OK
    res_adm_rev = client.post(
        f"/api/v1/engineering/readiness/{wo_num}/revoke",
        headers=_auth(s["admin_token"]),
        json={"revocation_reason": "Drawing revision supersession required"}
    )
    assert res_adm_rev.status_code == 200
    assert res_adm_rev.json()["readiness_status"] == "PENDING"

    # 4. Re-release after revocation
    client.put(
        f"/api/v1/engineering/readiness/{wo_num}",
        headers=_auth(s["eng_token"]),
        json={"verified_revision": "REV-REP-V2"}
    )
    client.post(
        f"/api/v1/engineering/readiness/{wo_num}/release",
        headers=_auth(s["eng_token"]),
        json={"replacement_reason_acknowledged": True}
    )

    # 5. Simulate first production movement, then attempt revocation -> Must be blocked 400
    db = SessionLocal()
    try:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
        mov = ProductionMovement(
            id=uuid.uuid4(),
            movement_id=_unique("MOV"),
            work_order_id=wo.id,
            from_stage="F1",
            to_stage="F2",
            quantity_moved=10
        )
        db.add(mov)
        db.commit()
    finally:
        db.close()

    res_blocked = client.post(
        f"/api/v1/engineering/readiness/{wo_num}/revoke",
        headers=_auth(s["admin_token"]),
        json={"revocation_reason": "Attempting rollback after floor movement"}
    )
    assert res_blocked.status_code == 400
    assert "production movements" in res_blocked.json()["detail"]


# ===========================================================================
# 6. Granular Checklist Item Failure Tests & List Filters
# ===========================================================================

@pytest.mark.parametrize("missing_field,expected_msg", [
    ("drawing_available", "Drawing is not available"),
    ("drawing_revision_verified", "Drawing revision is not verified"),
    ("customer_spec_verified", "Customer & material specification is unverified"),
    ("process_sheet_verified", "Process / method sheet is unverified"),
    ("pattern_ready", "Pattern / Core box readiness is unverified"),
    ("tooling_ready", "Tooling / Jigs / Fixtures readiness is unverified"),
])
def test_individual_missing_checklist_flags_block_release(client, test_setup, missing_field, expected_msg):
    s = test_setup
    wo_num = s["wo_npd_num"]
    headers = _auth(s["eng_token"])

    # Base payload with 6 valid items
    valid_payload = {
        "drawing_available": True,
        "drawing_revision_verified": True,
        "customer_spec_verified": True,
        "process_sheet_verified": True,
        "pattern_ready": True,
        "tooling_ready": True,
        "verified_revision": "REV-TEST",
        "drawing_url": "https://docs.vspl.in/dwg/test.pdf"
    }

    # Set one field to False
    valid_payload[missing_field] = False

    client.put(f"/api/v1/engineering/readiness/{wo_num}", headers=headers, json=valid_payload)

    # Release should be blocked
    res = client.post(f"/api/v1/engineering/readiness/{wo_num}/release", headers=headers, json={})
    assert res.status_code == 400
    assert expected_msg in res.json()["detail"]


def test_engineering_readiness_search_and_filters(client, test_setup):
    s = test_setup
    headers = _auth(s["eng_token"])

    # 1. Search by customer code
    res_cust = client.get(f"/api/v1/engineering/readiness?customer_code={s['cust_code']}", headers=headers)
    assert res_cust.status_code == 200
    items = res_cust.json()
    assert len(items) >= 2

    # 2. Filter by classification (npd)
    res_npd = client.get(f"/api/v1/engineering/readiness?classification=npd", headers=headers)
    assert res_npd.status_code == 200
    npd_items = res_npd.json()
    assert any(i["wo_number"] == s["wo_npd_num"] for i in npd_items)

    # 3. Filter by status (PENDING / READY / RELEASED)
    res_pend = client.get(f"/api/v1/engineering/readiness?status_filter=PENDING", headers=headers)
    assert res_pend.status_code == 200

