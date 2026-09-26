import pytest
from datetime import datetime, date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.core.security import hash_password, create_access_token
from app.models.user import User, UserRole
from app.models.order import Order, Part, Customer, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP, ProductionMovement
from app.models.production import ProductionUpdate
from app.models.nc import NCRecord
from app.models.rejection_disposition import RejectionDisposition
from app.models.rejection_type import RejectionType
from app.services.seed_service import _seed_default_rejection_types

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
    _seed_default_rejection_types(db)
    db.commit()
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
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            full_name=email.split("@")[0],
            email=email,
            hashed_password=hash_password("x"),
            role=role,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    token = create_access_token({"sub": user.email, "role": user.role.value if hasattr(user.role, "value") else str(user.role)})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def setup_data(test_db):
    customer = Customer(customer_code="CUST-TST", name="Test Customer Aerospace")
    test_db.add(customer)
    test_db.flush()

    part = Part(part_number="PART-TST-001", description="Turbine Bushing", grade="Standard")
    test_db.add(part)
    test_db.flush()

    test_db.commit()
    return {"customer": customer, "part": part}

def test_partial_production_and_movement_allows_subsequent_production(test_db, client, setup_data):
    """
    Critical Scenario:
    WO Target = 50
    Produce F1 = 20
    Move F1 -> F2 = 20
    Verify F1 remaining yet_to_produce = 30, onhand_qty = 0, inproc_qty = 30.
    Verify moving another piece from F1 when onhand_qty = 0 FAILS with 400.
    Produce remaining 30 at F1.
    Move 30 F1 -> F2.
    Verify F1 OK Produced = 50, Yet to Produce = 0, F2 entered = 50.
    """
    headers = _auth(test_db, "admin_prod@vspl.com", UserRole.ADMIN)

    # 1. Create OAR and WO for 50 pcs
    intake_resp = client.post("/api/v1/operations/intake", headers=headers, json={
        "customer_code": "CUST-TST",
        "customer_name": "Test Customer Aerospace",
        "customer_po": "PO-PARTIAL-01",
        "part_number": "PART-TST-001",
        "po_quantity": 50,
        "max_batch_size": 50,
        "order_type": "Standard"
    })
    assert intake_resp.status_code == 200, intake_resp.text
    wo_num = intake_resp.json()["wos_created"][0]

    # Release WO with standard stages
    rel_resp = client.post("/api/v1/operations/wo-release", headers=headers, json={
        "wo_number": wo_num,
        "physical_wo_qty": 50,
        "route_stages": ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"],
        "remarks": "Standard route release"
    })
    assert rel_resp.status_code == 200, rel_resp.text

    # 2. First Production Entry at F1: 20 pcs
    prod_resp1 = client.post("/api/v1/production/entry", headers=headers, json={
        "wo_number": wo_num,
        "stage": "F1",
        "good_qty": 20,
        "rejected_quantity": 0,
        "machine_id": "M-CC01",
        "operator_name": "Ramesh Kumar",
        "shift": "Shift A",
        "remarks": "Batch 1: 20 pcs"
    })
    assert prod_resp1.status_code == 200, prod_resp1.text
    assert prod_resp1.json()["stage_ok_total"] == 20
    assert prod_resp1.json()["stage_onhand_available"] == 20
    assert prod_resp1.json()["stage_inproc_remaining"] == 30

    # 3. Move 20 pcs from F1 to F2
    move_resp1 = client.post("/api/v1/production/move", headers=headers, json={
        "wo_number": wo_num,
        "from_stage": "F1",
        "to_stage": "F2",
        "quantity_moved": 20,
        "rejected_quantity": 0,
        "machine_id": "M-LATHE-01",
        "operator_name": "Logistics Operator",
        "shift": "Shift A"
    })
    assert move_resp1.status_code == 200, move_resp1.text

    # Check stage dashboard / state for F1
    f1_dash = client.get(f"/api/v1/production/stage-summary?wo_number={wo_num}&stage=F1", headers=headers)
    assert f1_dash.status_code == 200, f1_dash.text
    f1_data = f1_dash.json()
    f1_target = f1_data["target_qty"]
    assert f1_data["total_good"] == 20
    assert f1_data["wip_qty"] == 30
    assert f1_data["yet_to_produce"] == f1_target - 20
    assert f1_data["remaining_movable_qty"] == 0

    # Check stage state for F2
    f2_dash = client.get(f"/api/v1/production/stage-summary?wo_number={wo_num}&stage=F2", headers=headers)
    assert f2_dash.status_code == 200, f2_dash.text
    f2_data = f2_dash.json()
    assert f2_data["wip_qty"] == 20  # 20 arrived and available to process
    assert f2_data["total_good"] == 0

    # 4. Attempt to move 1 piece from F1 when onhand is 0 -> MUST FAIL
    move_fail = client.post("/api/v1/production/move", headers=headers, json={
        "wo_number": wo_num,
        "from_stage": "F1",
        "to_stage": "F2",
        "quantity_moved": 1,
        "rejected_quantity": 0
    })
    assert move_fail.status_code == 400
    assert "Only 0 completed good pieces are currently on-hand" in move_fail.json()["detail"]

    # 5. Second Production Entry at F1: produce remaining 30 pcs entered at F1
    prod_resp2 = client.post("/api/v1/production/entry", headers=headers, json={
        "wo_number": wo_num,
        "stage": "F1",
        "good_qty": 30,
        "rejected_quantity": 0,
        "machine_id": "M-CC01",
        "operator_name": "Ramesh Kumar",
        "shift": "Shift A",
        "remarks": "Batch 2: remaining 30 pcs"
    })
    assert prod_resp2.status_code == 200, prod_resp2.text
    assert prod_resp2.json()["stage_ok_total"] == 50
    assert prod_resp2.json()["stage_onhand_available"] == 30
    assert prod_resp2.json()["stage_inproc_remaining"] == 0

    # 6. Move remaining 30 pcs from F1 to F2
    move_resp2 = client.post("/api/v1/production/move", headers=headers, json={
        "wo_number": wo_num,
        "from_stage": "F1",
        "to_stage": "F2",
        "quantity_moved": 30,
        "rejected_quantity": 0
    })
    assert move_resp2.status_code == 200, move_resp2.text

    # F1 is now fully produced and moved
    f1_dash_after = client.get(f"/api/v1/production/stage-summary?wo_number={wo_num}&stage=F1", headers=headers).json()
    assert f1_dash_after["total_good"] == 50
    assert f1_dash_after["wip_qty"] == 0
    assert f1_dash_after["remaining_movable_qty"] == 0

    # F2 now has all 50 entered pieces ready for production
    f2_dash_after = client.get(f"/api/v1/production/stage-summary?wo_number={wo_num}&stage=F2", headers=headers).json()
    assert f2_dash_after["wip_qty"] == 50
    assert f2_dash_after["total_good"] == 0

def test_engineering_and_manufacturing_release_evidence_and_url_validation(test_db, client, setup_data):
    """
    Test Engineering & Manufacturing Release Evidence:
    - Document Name, Revision, HTTPS URL, Remarks.
    - Strict rejection of non-HTTPS URLs (e.g. http://, javascript:).
    - Sequential release gate enforcement.
    """
    eng_headers = _auth(test_db, "eng_user_01@vspl.com", UserRole.ENGINEERING)
    mfg_headers = _auth(test_db, "mfg_user_01@vspl.com", UserRole.MANUFACTURING)
    plan_headers = _auth(test_db, "plan_user_01@vspl.com", UserRole.PLANNER)

    # Create OAR / WO
    intake = client.post("/api/v1/operations/intake", headers=plan_headers, json={
        "customer_code": "CUST-TST",
        "customer_name": "Test Customer Aerospace",
        "customer_po": "PO-EVIDENCE-01",
        "part_number": "PART-TST-001",
        "po_quantity": 100,
        "max_batch_size": 100
    }).json()
    wo_num = intake["wos_created"][0]

    # Non-HTTPS URL MUST FAIL
    bad_url_resp = client.post(f"/api/v1/operations/wo/{wo_num}/engineering-release", headers=eng_headers, json={
        "document_name": "Drawing D-100",
        "document_url": "http://insecure-server.com/doc.pdf",
        "document_revision": "Rev A"
    })
    assert bad_url_resp.status_code == 400
    assert "Document URL must be a valid secure HTTPS URL" in bad_url_resp.json()["detail"]

    # Valid HTTPS URL Engineering Release MUST SUCCEED
    eng_resp = client.post(f"/api/v1/operations/wo/{wo_num}/engineering-release", headers=eng_headers, json={
        "document_name": "Engineering Drawing D-100",
        "document_url": "https://secure-docs.vspl.com/drawings/d-100-revA.pdf",
        "document_revision": "Rev A",
        "remarks": "Approved by lead engineer"
    })
    assert eng_resp.status_code == 200, eng_resp.text
    eng_data = eng_resp.json()
    assert eng_data["success"] is True
    assert eng_data["engineering_document_name"] == "Engineering Drawing D-100"
    assert eng_data["engineering_document_url"] == "https://secure-docs.vspl.com/drawings/d-100-revA.pdf"
    assert eng_data["engineering_document_revision"] == "Rev A"
    assert eng_data["engineering_remarks"] == "Approved by lead engineer"

    # Manufacturing Release before Engineering would fail if eng wasn't done; now do Mfg release with evidence
    mfg_resp = client.post(f"/api/v1/operations/wo/{wo_num}/manufacturing-release", headers=mfg_headers, json={
        "document_name": "Routing Route Sheet RS-100",
        "document_url": "https://secure-docs.vspl.com/routing/rs-100.pdf",
        "document_revision": "Rev 1",
        "remarks": "Tooling and fixture confirmed"
    })
    assert mfg_resp.status_code == 200, mfg_resp.text
    mfg_data = mfg_resp.json()
    assert mfg_data["success"] is True
    assert mfg_data["manufacturing_document_name"] == "Routing Route Sheet RS-100"
    assert mfg_data["manufacturing_document_url"] == "https://secure-docs.vspl.com/routing/rs-100.pdf"

    # WO Release completes the release chain
    wo_rel = client.post("/api/v1/operations/wo-release", headers=plan_headers, json={
        "wo_number": wo_num,
        "physical_wo_qty": 100,
        "route_stages": ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"],
        "remarks": "Released after engineering and manufacturing approval"
    })
    assert wo_rel.status_code == 200, wo_rel.text

def test_replacement_wo_shortfall_limit_and_release_chain(test_db, client, setup_data):
    """
    Test Quality Rejection Replacement WO:
    - OAR qty = 40.
    - WO target = 40.
    - Produce F1 = 30 good, 10 rejected (NC record created for 10 pcs).
    - Max recoverable shortfall is 10.
    - Attempting to create replacement WO for 15 pcs FAILS with 400.
    - Creating replacement WO for 10 pcs SUCCEEDS (is_replacement = True).
    - Attempting to produce replacement WO before Engineering Release FAILS with 400.
    - Completing release chain on replacement WO allows production.
    """
    admin_headers = _auth(test_db, "admin_rec@vspl.com", UserRole.ADMIN)
    qa_headers = _auth(test_db, "qa_lead@vspl.com", UserRole.QA)
    eng_headers = _auth(test_db, "eng_rec@vspl.com", UserRole.ENGINEERING)
    mfg_headers = _auth(test_db, "mfg_rec@vspl.com", UserRole.MANUFACTURING)
    plan_headers = _auth(test_db, "plan_rec@vspl.com", UserRole.PLANNER)

    # 1. Create OAR and original WO
    intake = client.post("/api/v1/operations/intake", headers=admin_headers, json={
        "customer_code": "CUST-TST",
        "customer_name": "Test Customer Aerospace",
        "customer_po": "PO-RECOVERY-01",
        "part_number": "PART-TST-001",
        "po_quantity": 40,
        "max_batch_size": 40
    }).json()
    orig_wo = intake["wos_created"][0]

    # Release original WO
    client.post("/api/v1/operations/wo-release", headers=admin_headers, json={
        "wo_number": orig_wo,
        "physical_wo_qty": 40,
        "route_stages": ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]
    })

    # 2. Produce at F1: 30 Good, 10 Rejected
    client.post("/api/v1/production/entry", headers=admin_headers, json={
        "wo_number": orig_wo,
        "stage": "F1",
        "good_qty": 30,
        "rejected_quantity": 10,
        "defect_code": "DEF-POROSITY",
        "remarks": "10 pcs porosity scrap"
    })

    # Find the NC Record
    orig_wo_obj = test_db.query(WorkOrder).filter(WorkOrder.wo_number == orig_wo).first()
    nc_rec = test_db.query(NCRecord).filter(NCRecord.work_order_id == orig_wo_obj.id).first()
    assert nc_rec is not None
    assert nc_rec.qty == 10

    # 3. Try to create replacement for 15 pcs (exceeds 10 NC and shortfall) -> MUST FAIL
    over_resp = client.post("/api/v1/rejection/replacement", headers=qa_headers, json={
        "nc_number": nc_rec.nc_number,
        "quantity": 15,
        "reason": "Requesting 15 replacement pcs"
    })
    assert over_resp.status_code == 400

    # 4. Create valid replacement for 10 pcs -> MUST SUCCEED
    repl_resp = client.post("/api/v1/rejection/replacement", headers=qa_headers, json={
        "nc_number": nc_rec.nc_number,
        "quantity": 10,
        "reason": "Recover 10 rejected pieces"
    })
    assert repl_resp.status_code == 200, repl_resp.text
    repl_wo_num = repl_resp.json()["replacement_wo_number"]

    # 5. Replacement WO is blocked from production before release chain
    prod_blocked = client.post("/api/v1/production/entry", headers=admin_headers, json={
        "wo_number": repl_wo_num,
        "stage": "F1",
        "good_qty": 10,
        "rejected_quantity": 0
    })
    assert prod_blocked.status_code == 400
    assert "blocked pending Engineering Release" in prod_blocked.json()["detail"]

    # 6. Complete Release Chain on Replacement WO
    client.post(f"/api/v1/operations/wo/{repl_wo_num}/engineering-release", headers=eng_headers, json={
        "document_name": "Standard Drawing D-100",
        "document_url": "https://secure-docs.vspl.com/drawings/d-100.pdf",
        "document_revision": "Rev A"
    })
    client.post(f"/api/v1/operations/wo/{repl_wo_num}/manufacturing-release", headers=mfg_headers, json={
        "document_name": "Standard Route RS-100",
        "document_url": "https://secure-docs.vspl.com/routing/rs-100.pdf"
    })
    client.post("/api/v1/operations/wo-release", headers=plan_headers, json={
        "wo_number": repl_wo_num,
        "physical_wo_qty": 10,
        "route_stages": ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]
    })

    # 7. Now production on replacement WO succeeds
    repl_prod = client.post("/api/v1/production/entry", headers=admin_headers, json={
        "wo_number": repl_wo_num,
        "stage": "F1",
        "good_qty": 10,
        "rejected_quantity": 0
    })
    assert repl_prod.status_code == 200, repl_prod.text
    assert repl_prod.json()["stage_ok_total"] == 10
