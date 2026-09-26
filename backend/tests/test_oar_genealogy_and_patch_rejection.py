import pytest
from datetime import datetime, date
from fastapi import HTTPException
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
from app.models.production_movement import StageWIP
from app.models.production import ProductionUpdate
from app.models.nc import NCRecord
from app.services.seed_service import _seed_default_rejection_types
from app.services.work_order_service import WorkOrderService
from app.services.operations_service import OperationsService
from app.services.production_service import ProductionService
from app.services.rejection_service import RejectionService
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest
from app.schemas.rejection import ReplacementCreate
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
def auth_headers(test_db):
    return _auth(test_db, "admin@vspl.com", UserRole.ADMIN)

@pytest.fixture
def oar_test_data(test_db: Session):
    db_session = test_db
    # Create test customer & part
    cust = Customer(
        customer_code="CUST-GENEALOGY",
        name="Genealogy Test Customer",
        is_active=True
    )
    part = Part(
        part_number="PART-GENEALOGY-100",
        description="Genealogy Rotor Test Part",
        grade="A356-T6"
    )
    db_session.add_all([cust, part])
    db_session.flush()

    # OAR with po_qty = 10
    order = Order(
        oar_number="OAR-GEN-001",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-GEN-2026",
        po_qty=10,
        max_batch_size=10,
        delivery_date=date(2026, 12, 31),
        order_type="regular",
        status=OrderStatus.ACCEPT
    )
    db_session.add(order)
    db_session.flush()

    # Original WO for target 10
    wo1 = WorkOrder(
        wo_number="WO-GEN-001",
        order_id=order.id,
        physical_wo_qty=10,
        current_stage="F1",
        projected_final_good=10,
        status=WOStatus.IN_PRODUCTION,
        is_replacement=False,
        released_by="Planner Admin"
    )
    db_session.add(wo1)
    db_session.flush()

    # Setup routes for WO-GEN-001
    stages = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
    for idx, stg in enumerate(stages, start=1):
        db_session.add(WORoute(
            work_order_id=wo1.id,
            stage=stg,
            sequence=idx,
            stage_target_qty=10,
            cumulative_ent_qty=10 if idx == 1 else 0,
            cumulative_inproc_qty=10 if idx == 1 else 0,
            stage_status="In-Progress" if idx == 1 else "Pending"
        ))
        db_session.add(StageWIP(
            work_order_id=wo1.id,
            stage=stg,
            ent_qty=10 if idx == 1 else 0,
            ok_qty=0,
            inproc_qty=10 if idx == 1 else 0,
            onhand_qty=0,
            rejected_qty=0,
            available_wip=10 if idx == 1 else 0,
            received_qty=10 if idx == 1 else 0
        ))
    db_session.commit()

    return {
        "order": order,
        "wo1": wo1,
        "customer": cust,
        "part": part
    }


def test_oar_production_genealogy_exact_business_scenario(test_db: Session, oar_test_data):
    """Verifies the exact user prompt scenario:
    OAR = 10
    Original WO:
      F1 Produced 10 -> Good 8, Rejected 2
      F3 later rejects 1
      Final good contribution = 7
    Patch WO:
      Produced 3 -> Good 2, Rejected 1
      Final good contribution = 2
    OAR Aggregate:
      WOs = 2
      Total production entries = 13
      Total rejected = 4
      Final OAR fulfillment = 9
      Remaining shortfall = 1
      Subsequent Patch WO cannot exceed shortfall of 1.
    """
    order = oar_test_data["order"]
    wo1 = oar_test_data["wo1"]
    qa_user = User(
        id=None,
        email="qa@vspl.com",
        full_name="Quality Auditor",
        role=UserRole.QA,
        is_active=True
    )

    # 1. Original WO: Record F1 Production (10 total: 8 Good, 2 Rejected)
    prod_res = ProductionService.record_stage_production(
        test_db,
        RecordStageProductionRequest(
            wo_number=wo1.wo_number,
            stage="F1",
            good_qty=8,
            rejected_quantity=2,
            defect_code="DEF-BLOWHOLE"
        ),
        current_user=qa_user
    )
    assert prod_res.good_qty == 8
    assert prod_res.rejected_quantity == 2

    # Verify NC Record created for the 2 rejected pieces
    nc1 = test_db.query(NCRecord).filter(NCRecord.work_order_id == wo1.id, NCRecord.stage == "F1").first()
    assert nc1 is not None
    assert nc1.qty == 2

    # Move 8 pieces F1 -> F2
    ProductionService.move_parts(
        test_db,
        MovePartsRequest(
            wo_number=wo1.wo_number,
            from_stage="F1",
            to_stage="F2",
            quantity_moved=8,
            rejected_quantity=0,
            reason="Move to F2"
        ),
        current_user=qa_user
    )

    # Move from F2 -> F3: 7 Good moved, 1 Rejected at F2/F3 (creating second NC record)
    ProductionService.move_parts(
        test_db,
        MovePartsRequest(
            wo_number=wo1.wo_number,
            from_stage="F2",
            to_stage="F3",
            quantity_moved=7,
            rejected_quantity=1,
            defect_code="DEF-DIM-OUT",
            reason="Move to F3 with 1 dimensional rejection"
        ),
        current_user=qa_user
    )

    # Move 7 good pieces F3 -> SP -> FI -> PACKING / BSR (completing final route to packing)
    ProductionService.move_parts(
        test_db,
        MovePartsRequest(wo_number=wo1.wo_number, from_stage="F3", to_stage="SP", quantity_moved=7, rejected_quantity=0, reason="Move to SP"),
        current_user=qa_user
    )
    ProductionService.move_parts(
        test_db,
        MovePartsRequest(wo_number=wo1.wo_number, from_stage="SP", to_stage="FI", quantity_moved=7, rejected_quantity=0, reason="Move to FI"),
        current_user=qa_user
    )
    ProductionService.move_parts(
        test_db,
        MovePartsRequest(wo_number=wo1.wo_number, from_stage="FI", to_stage="PACKING / BSR", quantity_moved=7, rejected_quantity=0, reason="Move to Packing"),
        current_user=qa_user
    )

    # Check Original WO state in OAR genealogy
    genealogy_1 = WorkOrderService.build_oar_summary(test_db, order)
    assert genealogy_1.num_wos == 1
    assert genealogy_1.num_original_wos == 1
    assert genealogy_1.num_patch_wos == 0
    assert genealogy_1.total_produced == 10
    assert genealogy_1.total_good == 8
    assert genealogy_1.total_rejected == 3  # 2 at F1 + 1 at F3
    assert genealogy_1.oar_fulfilled == 7   # 7 pieces completed route to Packing
    assert genealogy_1.oar_shortfall == 3   # 10 - 7 = 3

    # 2. Quality creates a Patch/Replacement WO for quantity 2 against nc1
    repl_res = RejectionService.create_replacement(
        test_db,
        ReplacementCreate(
            nc_number=nc1.nc_number,
            quantity=2,  # consume 2 from nc1
            reason="Customer urgency replacement"
        ),
        current_user=qa_user
    )
    patch_wo_number = repl_res.replacement_wo_number
    assert patch_wo_number is not None

    patch_wo = test_db.query(WorkOrder).filter(WorkOrder.wo_number == patch_wo_number).first()
    assert patch_wo is not None
    assert patch_wo.is_replacement is True
    assert patch_wo.source_wo_id == wo1.id

    # Release the Patch WO through release chain
    eng_user = User(id=None, email="eng@vspl.com", full_name="Lead Engineer", role=UserRole.ENGINEERING, is_active=True)
    mfg_user = User(id=None, email="mfg@vspl.com", full_name="Mfg Head", role=UserRole.MANUFACTURING, is_active=True)
    plan_user = User(id=None, email="planner@vspl.com", full_name="Master Planner", role=UserRole.PLANNER, is_active=True)

    OperationsService.engineering_release(test_db, patch_wo.wo_number, current_user=eng_user)
    OperationsService.manufacturing_release(test_db, patch_wo.wo_number, current_user=mfg_user)
    OperationsService.release_work_order(
        test_db,
        req=WOReleaseCreate(
            wo_number=patch_wo.wo_number,
            physical_wo_qty=3,
            route_stages=["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"],
            remarks="Released replacement WO"
        ),
        current_user=plan_user
    )

    # 3. Patch WO Production: Produced 3 -> Good 2, Rejected 1 at F1
    prod_patch = ProductionService.record_stage_production(
        test_db,
        RecordStageProductionRequest(
            wo_number=patch_wo.wo_number,
            stage="F1",
            good_qty=2,
            rejected_quantity=1,
            defect_code="DEF-POROSITY"
        ),
        current_user=qa_user
    )
    assert prod_patch.good_qty == 2
    assert prod_patch.rejected_quantity == 1

    # Move 2 good pieces of patch WO through to PACKING / BSR
    for from_s, to_s in [("F1", "F2"), ("F2", "F3"), ("F3", "SP"), ("SP", "FI"), ("FI", "PACKING / BSR")]:
        ProductionService.move_parts(
            test_db,
            MovePartsRequest(wo_number=patch_wo.wo_number, from_stage=from_s, to_stage=to_s, quantity_moved=2, rejected_quantity=0),
            current_user=qa_user
        )

    # 4. Comprehensive OAR Genealogy Verification
    oar_gen = WorkOrderService.build_oar_summary(test_db, order)

    # High-level OAR metrics
    assert oar_gen.oar_qty == 10
    assert oar_gen.num_wos == 2
    assert oar_gen.num_original_wos == 1
    assert oar_gen.num_patch_wos == 1
    assert oar_gen.total_produced == 13  # 10 from original WO + 3 from patch WO
    assert oar_gen.total_rejected == 4  # 3 from original WO + 1 from patch WO (PATCH REJECTION INCLUDED)
    assert oar_gen.oar_fulfilled == 9   # 7 from original WO + 2 from patch WO
    assert oar_gen.oar_shortfall == 1   # 10 - 9 = 1

    # Individual Work Order Breakdown
    wo_summaries = {w.wo_number: w for w in oar_gen.work_orders}
    orig_sum = wo_summaries[wo1.wo_number]
    patch_sum = wo_summaries[patch_wo.wo_number]

    # Original WO verification
    assert orig_sum.wo_type == "ORIGINAL"
    assert orig_sum.is_replacement is False
    assert orig_sum.source_wo_number is None
    assert orig_sum.production_qty == 10
    assert orig_sum.good_qty == 8
    assert orig_sum.rejected_qty == 3
    assert orig_sum.final_good_contribution == 7
    assert orig_sum.release_status == "RELEASED"

    # Patch WO verification
    assert patch_sum.wo_type == "PATCH"
    assert patch_sum.is_replacement is True
    assert patch_sum.source_wo_number == wo1.wo_number
    assert patch_sum.production_qty == 3
    assert patch_sum.good_qty == 2
    assert patch_sum.rejected_qty == 1  # Proves patch rejection is tracked
    assert patch_sum.final_good_contribution == 2
    assert patch_sum.release_status == "RELEASED"

    # 5. Over-recovery protection:
    # First, verify undispositioned quantity check on nc_f2 (which has qty 1)
    nc_f2 = test_db.query(NCRecord).filter(NCRecord.work_order_id == wo1.id, NCRecord.stage == "F2").first()
    assert nc_f2 is not None

    with pytest.raises(HTTPException) as exc_info_nc:
        RejectionService.create_replacement(
            test_db,
            ReplacementCreate(
                nc_number=nc_f2.nc_number,
                quantity=2,  # Exceeds nc_f2 remaining undispositioned qty 1
                reason="Attempted NC over-consumption"
            ),
            current_user=qa_user
        )
    assert "Only 1 pieces remain undispositioned" in str(exc_info_nc.value.detail)

    # Second, verify OAR-level shortfall gate when NC has ample balance (e.g. qty 5)
    # but OAR remaining shortfall is only 1
    nc_large = NCRecord(
        nc_number="NC-GEN-LARGE-01",
        work_order_id=wo1.id,
        stage="F1",
        defect_code="DEF-POROSITY",
        qty=5,
        status="Open",
        source_type="MANUAL"
    )
    test_db.add(nc_large)
    test_db.flush()

    with pytest.raises(HTTPException) as exc_info_oar:
        RejectionService.create_replacement(
            test_db,
            ReplacementCreate(
                nc_number=nc_large.nc_number,
                quantity=2,  # NC has 5, but OAR shortfall is only 1!
                reason="Attempted OAR over-recovery"
            ),
            current_user=qa_user
        )
    assert "Maximum recoverable shortfall for OAR 'OAR-GEN-001' is 1 pieces" in str(exc_info_oar.value.detail)

    # Creating replacement for exact remaining shortfall (1 piece) MUST SUCCEED
    repl_2 = RejectionService.create_replacement(
        test_db,
        ReplacementCreate(
            nc_number=nc_large.nc_number,
            quantity=1,
            reason="Valid exact shortfall recovery"
        ),
        current_user=qa_user
    )
    assert repl_2.success is True
    assert repl_2.replacement_wo_number is not None
    assert repl_2.replacement_wo_number is not None


def test_oar_genealogy_rest_api_endpoint(client: TestClient, auth_headers, test_db: Session, oar_test_data):
    """Verifies that both /api/v1/operations/oars and /api/v1/operations/oars/{oar_number}/genealogy
    return the complete genealogy structure over REST API."""
    order = oar_test_data["order"]

    # 1. GET /api/v1/operations/oars
    res = client.get("/api/v1/operations/oars", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    matching_oar = next((o for o in data if o["oar_number"] == order.oar_number), None)
    assert matching_oar is not None
    assert "num_original_wos" in matching_oar
    assert "num_patch_wos" in matching_oar
    assert "total_produced" in matching_oar
    assert "total_rejected" in matching_oar
    assert "oar_fulfilled" in matching_oar
    assert "oar_shortfall" in matching_oar

    # 2. GET /api/v1/operations/oars/{oar_number}/genealogy
    res_gen = client.get(f"/api/v1/operations/oars/{order.oar_number}/genealogy", headers=auth_headers)
    assert res_gen.status_code == 200
    gen_data = res_gen.json()
    assert gen_data["oar_number"] == order.oar_number
    assert gen_data["oar_qty"] == 10
    assert len(gen_data["work_orders"]) >= 1
    wo_item = gen_data["work_orders"][0]
    assert "wo_type" in wo_item
    assert "final_good_contribution" in wo_item
    assert "rejected_qty" in wo_item


def test_create_patch_wo_directly_from_oar_and_release_chain(client: TestClient, test_db: Session):
    """Verifies creating a Patch WO directly from an OAR with shortfall,
    verifying it is created as DRAFT/unreleased, enforcing the release gate,
    releasing it through Engineering -> Manufacturing -> WO Release,
    and recording production on the Patch WO."""
    planner_headers = _auth(test_db, 'planner@vspl.com', UserRole.PLANNER)
    eng_headers = _auth(test_db, 'eng@vspl.com', UserRole.ENGINEERING)
    mfg_headers = _auth(test_db, 'mfg@vspl.com', UserRole.MANUFACTURING)
    floor_headers = _auth(test_db, 'operator@vspl.com', UserRole.OPERATOR)

    cust = Customer(customer_code="CUST-PATCH-TEST", name="Patch Test Customer", is_active=True)
    part = Part(part_number="PART-PATCH-01", description="Patch Part", grade="SS304")
    test_db.add_all([cust, part])
    test_db.flush()

    order = Order(
        oar_number="OAR-PATCH-001",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-PATCH-001",
        po_qty=5,
        max_batch_size=5,
        status=OrderStatus.ACCEPT,
        delivery_date=date.today()
    )
    test_db.add(order)
    test_db.flush()

    orig_wo = WorkOrder(
        wo_number="WO-PATCH-ORIG",
        order_id=order.id,
        physical_wo_qty=5,
        current_stage="F1",
        projected_final_good=5,
        status=WOStatus.IN_PRODUCTION,
        is_replacement=False,
        released_by="Planner",
        release_date=datetime.now(),
        engineering_released_at=datetime.now(),
        manufacturing_released_at=datetime.now()
    )
    test_db.add(orig_wo)
    test_db.flush()

    route = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]
    for seq, stg in enumerate(route, 1):
        test_db.add(WORoute(work_order_id=orig_wo.id, stage=stg, sequence=seq, stage_target_qty=5))
    test_db.add(StageWIP(
        work_order_id=orig_wo.id, stage="F1", ent_qty=5, ok_qty=0, inproc_qty=5, onhand_qty=0, rejected_qty=0, available_wip=5
    ))
    test_db.commit()

    # Step 1: Record production on original WO at F1: Good = 2, Rejected = 3
    prod_resp = client.post(
        "/api/v1/production/entry",
        headers=floor_headers,
        json={
            "wo_number": "WO-PATCH-ORIG",
            "stage": "F1",
            "good_qty": 2,
            "rejected_quantity": 3,
            "defect_code": "DEF-POROSITY",
            "remarks": "F1 trial scrap 3 pieces"
        }
    )
    assert prod_resp.status_code == 200

    # Verify OAR state: Shortfall = 3 (or 5 before terminal completion)
    oar_resp = client.get(f"/api/v1/operations/oars/{order.oar_number}/genealogy", headers=planner_headers)
    assert oar_resp.status_code == 200
    assert oar_resp.json()["total_produced"] == 5
    assert oar_resp.json()["total_good"] == 2
    assert oar_resp.json()["total_rejected"] == 3
    shortfall = oar_resp.json()["oar_shortfall"]
    assert shortfall >= 3

    # Step 2: Create Patch WO via /api/v1/rejection/replacement using oar_number
    patch_resp = client.post(
        "/api/v1/rejection/replacement",
        headers=planner_headers,
        json={
            "oar_number": order.oar_number,
            "source_wo_number": orig_wo.wo_number,
            "quantity": 3,
            "reason": "Replacement for F1 rejections",
            "remarks": "Created from OAR genealogy shortfall action"
        }
    )
    assert patch_resp.status_code == 200
    patch_data = patch_resp.json()
    patch_wo_num = patch_data["replacement_wo_number"]
    assert patch_data["quantity"] == 3
    assert patch_data["original_wo_number"] == "WO-PATCH-ORIG"
    assert patch_data["oar_number"] == order.oar_number

    # Step 3: Verify Patch WO is DRAFT / unreleased
    patch_wo = test_db.query(WorkOrder).filter(WorkOrder.wo_number == patch_wo_num).first()
    assert patch_wo is not None
    assert patch_wo.is_replacement is True
    assert patch_wo.physical_wo_qty == 3
    assert patch_wo.release_date is None
    assert patch_wo.released_by is None
    assert patch_wo.engineering_released_at is None
    assert patch_wo.manufacturing_released_at is None

    # Step 4: Attempting production before release must fail
    blocked_prod = client.post(
        "/api/v1/production/entry",
        headers=floor_headers,
        json={
            "wo_number": patch_wo_num,
            "stage": "F1",
            "good_qty": 3,
            "rejected_quantity": 0
        }
    )
    assert blocked_prod.status_code == 400
    assert "blocked pending Engineering Release" in blocked_prod.json()["detail"]

    # Step 5: Engineering Release
    eng_res = client.post(
        f"/api/v1/operations/wo/{patch_wo_num}/engineering-release",
        headers=eng_headers,
        json={"remarks": "Engineering drawing approved"}
    )
    assert eng_res.status_code == 200

    # Step 6: Manufacturing Release
    mfg_res = client.post(
        f"/api/v1/operations/wo/{patch_wo_num}/manufacturing-release",
        headers=mfg_headers,
        json={"remarks": "Tooling and setup verified"}
    )
    assert mfg_res.status_code == 200

    # Step 7: WO Release
    wo_rel_res = client.post(
        "/api/v1/operations/wo-release",
        headers=planner_headers,
        json={
            "wo_number": patch_wo_num,
            "physical_wo_qty": 3,
            "route_stages": ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"],
            "remarks": "Patch WO Released for floor production"
        }
    )
    assert wo_rel_res.status_code == 200

    # Step 8: Production entry on Patch WO succeeds
    patch_prod = client.post(
        "/api/v1/production/entry",
        headers=floor_headers,
        json={
            "wo_number": patch_wo_num,
            "stage": "F1",
            "good_qty": 3,
            "rejected_quantity": 0,
            "remarks": "Patch WO F1 production completed"
        }
    )
    assert patch_prod.status_code == 200

    # Step 9: Verify genealogy reflects both WOs under same OAR
    final_gen = client.get(f"/api/v1/operations/oars/{order.oar_number}/genealogy", headers=planner_headers).json()
    assert final_gen["num_wos"] == 2
    assert final_gen["num_original_wos"] == 1
    assert final_gen["num_patch_wos"] == 1
    assert final_gen["total_produced"] == 8
    assert final_gen["total_good"] == 5
    assert final_gen["total_rejected"] == 3
    assert len(final_gen["work_orders"]) == 2
    assert final_gen["work_orders"][0]["wo_type"] == "ORIGINAL"
    assert final_gen["work_orders"][1]["wo_type"] == "PATCH"

