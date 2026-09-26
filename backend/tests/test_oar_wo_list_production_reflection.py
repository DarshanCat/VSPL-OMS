import pytest
from datetime import datetime, date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.core.security import hash_password, create_access_token
from app.models.user import User, UserRole
from app.models.order import Order, Customer, Part, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP, ProductionMovement
from app.models.production import ProductionUpdate
from app.models.nc import NCRecord
from app.services.seed_service import _seed_default_rejection_types
from app.services.work_order_service import WorkOrderService
from app.services.operations_service import OperationsService
from app.services.production_service import ProductionService
from app.services.rejection_service import RejectionService
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest
from app.schemas.operations import WOReleaseCreate

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
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
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
    token = create_access_token({"sub": user.email, "role": user.role.value if hasattr(user.role, "value") else str(user.role)})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def oar_test_data(test_db: Session):
    cust = Customer(customer_code="CUST-GEN-01", name="Genealogy Test Customer", is_active=True)
    part = Part(part_number="PART-GEN-100", description="Genealogy Rotor Part", grade="A356-T6")
    test_db.add_all([cust, part])
    test_db.flush()

    order = Order(
        oar_number="OAR-TEST-001",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-TEST-2026",
        po_qty=10,
        max_batch_size=10,
        delivery_date=date(2026, 12, 31),
        order_type="regular",
        status=OrderStatus.ACCEPT
    )
    test_db.add(order)
    test_db.flush()

    wo1 = WorkOrder(
        wo_number="WO-TEST-001",
        order_id=order.id,
        physical_wo_qty=10,
        current_stage="F1",
        projected_final_good=10,
        status=WOStatus.IN_PRODUCTION,
        is_replacement=False,
        released_by="Planner Admin"
    )
    test_db.add(wo1)
    test_db.flush()

    stages = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
    for idx, stg in enumerate(stages, start=1):
        test_db.add(WORoute(
            work_order_id=wo1.id,
            stage=stg,
            sequence=idx,
            stage_target_qty=10,
            cumulative_ent_qty=10 if idx == 1 else 0,
            cumulative_inproc_qty=10 if idx == 1 else 0,
            stage_status="In-Progress" if idx == 1 else "Pending"
        ))
        test_db.add(StageWIP(
            work_order_id=wo1.id,
            stage=stg,
            ent_qty=10 if idx == 1 else 0,
            ok_qty=0,
            inproc_qty=10 if idx == 1 else 0,
            onhand_qty=0,
            rejected_qty=0,
            available_wip=10 if idx == 1 else 0
        ))
    test_db.commit()

    return {"customer": cust, "part": part, "order": order, "wo1": wo1}


# ===========================================================================
# TEST 1: OAR/WO List reflects Good = 5, Rejected = 5 immediately after commit
# ===========================================================================

def test_oar_wo_list_reflects_latest_production_and_rejection(client: TestClient, test_db: Session, oar_test_data):
    """
    Scenario:
    WO Qty = 10
    Before production: Good = 0, Rejected = 0
    Record: Good = 5, Rejected = 5
    Then query /api/v1/operations/oars and genealogy endpoints.
    Assert:
      WO Qty = 10
      Production OK = 5
      Rejected = 5
      OAR fulfilled = 5
      OAR shortfall = 5
    """
    auth = _auth(test_db, "operator@vspl.com", UserRole.OPERATOR)
    order = oar_test_data["order"]
    wo1 = oar_test_data["wo1"]

    # 1. Verify before production: Good = 0, Rejected = 0
    res_before = client.get("/api/v1/operations/oars", headers=auth)
    assert res_before.status_code == 200
    oars_before = res_before.json()
    oar_b = next((o for o in oars_before if o["oar_number"] == order.oar_number), None)
    assert oar_b is not None
    assert oar_b["total_produced"] == 0
    assert oar_b["total_good"] == 0
    assert oar_b["total_rejected"] == 0
    assert oar_b["oar_fulfilled"] == 0
    assert oar_b["oar_shortfall"] == 10
    wo_b = oar_b["work_orders"][0]
    assert wo_b["allocated_qty"] == 10
    assert wo_b["good_qty"] == 0
    assert wo_b["rejected_qty"] == 0
    assert wo_b["final_good_contribution"] == 0

    # 2. Record Production Entry: Good = 5, Rejected = 5
    prod_payload = {
        "wo_number": wo1.wo_number,
        "stage": "F1",
        "good_qty": 5,
        "rejected_quantity": 5,
        "defect_code": "DEF-POROSITY",
        "machine_id": "M-CC01",
        "operator_name": "Ramesh Kumar",
        "shift": "Shift A"
    }
    res_prod = client.post("/api/v1/production/entry", json=prod_payload, headers=auth)
    assert res_prod.status_code == 200

    # 3. Query /api/v1/operations/oars at intermediate stage F1:
    # Production OK = 5, Rejected = 5, but OAR Fulfilled = 0 (material has NOT completed route to Packing yet)
    res_after = client.get("/api/v1/operations/oars", headers=auth)
    assert res_after.status_code == 200
    oars_after = res_after.json()
    oar_a = next((o for o in oars_after if o["oar_number"] == order.oar_number), None)
    assert oar_a is not None
    assert oar_a["oar_qty"] == 10
    assert oar_a["total_produced"] == 10  # 5 Good + 5 Rejected
    assert oar_a["total_good"] == 5       # Production OK = 5
    assert oar_a["total_rejected"] == 5   # Rejected = 5
    assert oar_a["oar_fulfilled"] == 0    # Intermediate stage F1 -> OAR Fulfilled = 0
    assert oar_a["oar_shortfall"] == 10   # Shortfall remains 10 until terminal route completed

    wo_a = oar_a["work_orders"][0]
    assert wo_a["wo_number"] == wo1.wo_number
    assert wo_a["allocated_qty"] == 10
    assert wo_a["production_qty"] == 10
    assert wo_a["good_qty"] == 5
    assert wo_a["rejected_qty"] == 5
    assert wo_a["ok_completed"] == 5
    assert wo_a["rejected"] == 5
    assert wo_a["final_good_contribution"] == 0

    # 4. Verify OAR genealogy endpoint at intermediate stage
    res_gen = client.get(f"/api/v1/operations/oars/{order.oar_number}/genealogy", headers=auth)
    assert res_gen.status_code == 200
    gen_data = res_gen.json()
    assert gen_data["total_good"] == 5
    assert gen_data["total_rejected"] == 5
    assert gen_data["oar_fulfilled"] == 0
    assert gen_data["oar_shortfall"] == 10

    # 5. Move the 5 good pieces along the full route: F1 -> F2 -> F3 -> SP -> FI -> PACKING / BSR
    for from_s, to_s in [("F1", "F2"), ("F2", "F3"), ("F3", "SP"), ("SP", "FI"), ("FI", "PACKING / BSR")]:
        client.post("/api/v1/production/move", json={
            "wo_number": wo1.wo_number,
            "from_stage": from_s,
            "to_stage": to_s,
            "quantity_moved": 5,
            "rejected_quantity": 0
        }, headers=auth)

    # 6. Query /api/v1/operations/oars after completing route to PACKING / BSR:
    # Now OAR Fulfilled = 5, OAR Shortfall = 5
    res_packed = client.get("/api/v1/operations/oars", headers=auth)
    assert res_packed.status_code == 200
    oar_p = next((o for o in res_packed.json() if o["oar_number"] == order.oar_number), None)
    assert oar_p["total_good"] == 5
    assert oar_p["total_rejected"] == 5
    assert oar_p["oar_fulfilled"] == 5   # Terminal route completed -> OAR Fulfilled = 5
    assert oar_p["oar_shortfall"] == 5   # 10 - 5 = 5
    assert oar_p["work_orders"][0]["final_good_contribution"] == 5


# ===========================================================================
# TEST 2: Repeated transactions — Immutable ledger verification
# ===========================================================================

def test_oar_wo_list_repeated_transactions_immutable_ledger(client: TestClient, test_db: Session, oar_test_data):
    """
    Transaction 1: Good = 5, Rejected = 0 -> OAR/WO List shows Good = 5, Rejected = 0
    Transaction 2: Good = 0, Rejected = 5 -> OAR/WO List shows Good = 5, Rejected = 5
    Both immutable ledger transactions remain visible.
    """
    auth = _auth(test_db, "operator@vspl.com", UserRole.OPERATOR)
    order = oar_test_data["order"]
    wo1 = oar_test_data["wo1"]

    # Transaction 1: Good = 5, Rejected = 0
    res1 = client.post("/api/v1/production/entry", json={
        "wo_number": wo1.wo_number,
        "stage": "F1",
        "good_qty": 5,
        "rejected_quantity": 0,
        "machine_id": "M-CC01",
        "operator_name": "Ramesh Kumar",
        "shift": "Shift A"
    }, headers=auth)
    assert res1.status_code == 200

    # Verify after Tx 1
    res_t1 = client.get("/api/v1/operations/oars", headers=auth)
    oar_t1 = next((o for o in res_t1.json() if o["oar_number"] == order.oar_number), None)
    assert oar_t1["total_good"] == 5
    assert oar_t1["total_rejected"] == 0
    assert oar_t1["work_orders"][0]["good_qty"] == 5
    assert oar_t1["work_orders"][0]["rejected_qty"] == 0

    # Transaction 2: Good = 0, Rejected = 5
    res2 = client.post("/api/v1/production/entry", json={
        "wo_number": wo1.wo_number,
        "stage": "F1",
        "good_qty": 0,
        "rejected_quantity": 5,
        "defect_code": "DEF-BLOWHOLE",
        "machine_id": "M-CC01",
        "operator_name": "Ramesh Kumar",
        "shift": "Shift A"
    }, headers=auth)
    assert res2.status_code == 200

    # Verify after Tx 2: Both transactions reflected (Good = 5, Rejected = 5)
    res_t2 = client.get("/api/v1/operations/oars", headers=auth)
    oar_t2 = next((o for o in res_t2.json() if o["oar_number"] == order.oar_number), None)
    assert oar_t2["total_produced"] == 10
    assert oar_t2["total_good"] == 5
    assert oar_t2["total_rejected"] == 5
    assert oar_t2["work_orders"][0]["good_qty"] == 5
    assert oar_t2["work_orders"][0]["rejected_qty"] == 5

    # Check WO Tracking Detail — both transaction history items exist
    res_track = client.get(f"/api/v1/work-orders/{wo1.wo_number}/tracking", headers=auth)
    assert res_track.status_code == 200
    track_data = res_track.json()
    prod_txs = [tx for tx in track_data["transactions"] if tx["transaction_type"] == "PRODUCTION_ENTRY"]
    assert len(prod_txs) == 2


# ===========================================================================
# TEST 3: Interleaved Production, Movement, and Cumulative Reflection
# ===========================================================================

def test_oar_wo_list_interleaved_production_movement_and_genealogy(client: TestClient, test_db: Session, oar_test_data):
    """
    Produce 5 at F1
    Move 5 from F1 -> F2
    Produce another 5 at F1
    OAR/WO List reflects cumulative production (10 OK total).
    """
    auth = _auth(test_db, "operator@vspl.com", UserRole.OPERATOR)
    order = oar_test_data["order"]
    wo1 = oar_test_data["wo1"]

    # 1. Produce 5 at F1
    client.post("/api/v1/production/entry", json={
        "wo_number": wo1.wo_number,
        "stage": "F1",
        "good_qty": 5,
        "rejected_quantity": 0,
    }, headers=auth)

    # 2. Move 5 from F1 -> F2
    client.post("/api/v1/production/move", json={
        "wo_number": wo1.wo_number,
        "from_stage": "F1",
        "to_stage": "F2",
        "quantity_moved": 5,
        "rejected_quantity": 0
    }, headers=auth)

    # 3. Produce another 5 at F1
    client.post("/api/v1/production/entry", json={
        "wo_number": wo1.wo_number,
        "stage": "F1",
        "good_qty": 5,
        "rejected_quantity": 0,
    }, headers=auth)

    # 4. Check OAR list while material is still in-process across F1 and F2:
    # Production OK = 10, but OAR Fulfilled = 0, OAR Shortfall = 10
    res_wip = client.get("/api/v1/operations/oars", headers=auth)
    assert res_wip.status_code == 200
    oar_w = next((o for o in res_wip.json() if o["oar_number"] == order.oar_number), None)
    assert oar_w["total_produced"] == 10
    assert oar_w["total_good"] == 10     # Production OK = 10
    assert oar_w["total_rejected"] == 0
    assert oar_w["oar_fulfilled"] == 0   # Intermediate stages -> Fulfilled = 0
    assert oar_w["oar_shortfall"] == 10  # Shortfall = 10

    # 5. Move remaining 5 from F1 -> F2 (so all 10 are at F2)
    client.post("/api/v1/production/move", json={"wo_number": wo1.wo_number, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 5, "rejected_quantity": 0}, headers=auth)

    # 6. Move all 10 from F2 -> F3 -> SP -> FI -> PACKING / BSR
    for from_s, to_s in [("F2", "F3"), ("F3", "SP"), ("SP", "FI"), ("FI", "PACKING / BSR")]:
        client.post("/api/v1/production/move", json={"wo_number": wo1.wo_number, "from_stage": from_s, "to_stage": to_s, "quantity_moved": 10, "rejected_quantity": 0}, headers=auth)

    # 7. Check OAR list after material reaches PACKING / BSR:
    res = client.get("/api/v1/operations/oars", headers=auth)
    assert res.status_code == 200
    oar = next((o for o in res.json() if o["oar_number"] == order.oar_number), None)
    assert oar["total_produced"] == 10
    assert oar["total_good"] == 10
    assert oar["total_rejected"] == 0
    assert oar["oar_fulfilled"] == 10    # Terminal route completed -> OAR Fulfilled = 10
    assert oar["oar_shortfall"] == 0     # 10 - 10 = 0

    wo = oar["work_orders"][0]
    assert wo["good_qty"] == 10
    assert wo["rejected_qty"] == 0
    assert wo["final_good_contribution"] == 10
