"""
VSPL SMES + OMS - Comprehensive Manufacturing Execution System Test Suite
Covers all business rules, dynamic routing variations, stage isolation, idempotency,
conservation of mass reconciliation, and Part 41 Exact Business Scenario.
"""

import pytest
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.core.database import Base
from app.models.user import User, UserRole
from app.models.order import Order, Part, Customer, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.production import ProductionUpdate
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.services.seed_service import _seed_default_rejection_types
from app.models.nc import NCRecord

from app.services.production_service import ProductionService
from app.services.packing_service import PackingService
from app.services.dispatch_service import DispatchService
from app.services.oms_integration_service import (
    OMSIntegrationService,
    calculate_stage_targets,
    match_route_stage,
    parse_route
)
from app.schemas.production import (
    MovePartsRequest,
    RecordStageProductionRequest
)
from app.schemas.packing import PackingUpdateRequest
from app.schemas.dispatch import DispatchRequest
from app.analytics.math_engine import (
    production_achievement,
    rejection_rate,
    yield_pct,
    reconciliation_variance
)
from app.analytics.ml_models import DelayPredictionModel

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    _seed_default_rejection_types(session)
    session.commit()

    cust = Customer(customer_code="CUST-BHEL", name="Bharat Heavy Electricals Ltd")
    part = Part(part_number="BRZ-BUSH-100", grade="PB2 / CuSn11P", description="Heavy Duty Bushing")
    session.add(cust)
    session.add(part)
    session.commit()

    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


# =========================================================================
# 1. DYNAMIC WO ROUTING & NEXT-STAGE RESOLUTION TESTS
# =========================================================================

def test_dynamic_wo_routes_resolution(db):
    """Verifies that each WO can have its own independent route (Route A, B, C)."""
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(
        oar_number="OAR-DYN-01", customer_id=cust.id, part_id=part.id,
        customer_po="PO-DYN", po_qty=100, max_batch_size=100, status=OrderStatus.ACCEPT
    )
    db.add(order)
    db.commit()

    # Route A: F1 -> F2 -> F3 -> FI -> PACKING -> DISPATCH
    route_a = ["F1", "F2", "F3", "FI", "PACKING", "DISPATCH"]
    targets_a = calculate_stage_targets(100, route=route_a)
    assert targets_a["FI"] == 100
    assert targets_a["F3"] > 100
    assert targets_a["F1"] >= targets_a["F2"]

    # Route B: F1 -> F2 -> SP -> FI -> BSR -> DISPATCH
    route_b = ["F1", "F2", "SP", "FI", "BSR", "DISPATCH"]
    matched_bsr = match_route_stage("BSR", route_b)
    assert matched_bsr == "BSR"

    # Route C: F1 -> F2 -> F3 -> SP -> FI -> PACKING -> BSR -> DISPATCH
    route_c = ["F1", "F2", "F3", "SP", "FI", "PACKING", "BSR", "DISPATCH"]
    matched_pack = match_route_stage("PACKING", route_c)
    assert matched_pack == "PACKING"


# =========================================================================
# 2. STAGE PRODUCTION ENTRY VS PHYSICAL MOVEMENT
# =========================================================================

def test_stage_production_entry_vs_movement(db):
    """Verifies that recording production completion and physical movement are separate events."""
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(oar_number="OAR-PROD-01", customer_id=cust.id, part_id=part.id, customer_po="PO-P1", po_qty=100, max_batch_size=100, status=OrderStatus.ACCEPT)
    db.add(order)
    db.commit()

    wo = WorkOrder(wo_number="WO-PROD-001", order_id=order.id, physical_wo_qty=100, current_stage="F1", status=WOStatus.RELEASED)
    db.add(wo)
    db.commit()

    for seq, stg in enumerate(["F1", "F2", "FI", "PACKING", "DISPATCH"], start=1):
        r = WORoute(work_order_id=wo.id, stage=stg, sequence=seq, stage_target_qty=100)
        db.add(r)
        wip = StageWIP(work_order_id=wo.id, stage=stg, ent_qty=100 if seq == 1 else 0, ok_qty=0, inproc_qty=100 if seq == 1 else 0, onhand_qty=0, rejected_qty=0, available_wip=100 if seq == 1 else 0)
        db.add(wip)
    db.commit()

    # Event 1: Record Stage Production (Good = 40, Rejection = 10 at F1)
    entry_res = ProductionService.record_stage_production(db, RecordStageProductionRequest(
        wo_number="WO-PROD-001",
        stage="F1",
        good_qty=40,
        rejected_quantity=10,
        defect_code="DEF-POROSITY",
        machine_id="M-CC01",
        remarks="First casting batch"
    ))
    assert entry_res.success is True
    assert entry_res.stage_ok_total == 40
    assert entry_res.stage_rejection_total == 10

    # Verify stage state: 40 good pieces are in On-Hand ready to move, 50 in-process remaining at F1
    f1_wip = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == "F1").first()
    assert f1_wip.ok_qty == 40
    assert f1_wip.rejected_qty == 10
    assert f1_wip.inproc_qty == 50
    assert f1_wip.onhand_qty == 40  # Held in On-Hand for later movement!

    # Event 2: Physical Movement to F2 (Transfer the 40 good pieces)
    mov_res = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-PROD-001",
        from_stage="F1",
        to_stage="F2",
        quantity_moved=40,
        rejected_quantity=0,
        machine_id="M-CC01"
    ))
    assert mov_res.success is True
    assert mov_res.to_stage_available_wip == 40


# =========================================================================
# 3. STAGE REJECTION ISOLATION & NON-PROPAGATION TESTS
# =========================================================================

def test_stage_rejection_isolation_and_nc(db):
    """Verifies that rejections at F1 vs F2 are isolated and do not move forward as good pieces."""
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(oar_number="OAR-REJ-01", customer_id=cust.id, part_id=part.id, customer_po="PO-R1", po_qty=100, max_batch_size=100, status=OrderStatus.ACCEPT)
    db.add(order)
    db.commit()

    wo = WorkOrder(wo_number="WO-REJ-001", order_id=order.id, physical_wo_qty=100, current_stage="F1", status=WOStatus.RELEASED)
    db.add(wo)
    db.commit()

    for seq, stg in enumerate(["F1", "F2", "F3", "FI", "PACKING", "DISPATCH"], start=1):
        db.add(WORoute(work_order_id=wo.id, stage=stg, sequence=seq, stage_target_qty=100))
        db.add(StageWIP(work_order_id=wo.id, stage=stg, ent_qty=100 if seq == 1 else 0, ok_qty=0, inproc_qty=100 if seq == 1 else 0, onhand_qty=0, rejected_qty=0, available_wip=100 if seq == 1 else 0))
    db.commit()

    # F1: Move 85 to F2, Reject 15 at F1
    res1 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-REJ-001", from_stage="F1", to_stage="F2", quantity_moved=85, rejected_quantity=15, defect_code="DEF-POROSITY"
    ))
    assert res1.success is True
    assert res1.to_stage_available_wip == 85  # ONLY good pieces move forward!

    # F2: Move 80 to F3, Reject 5 at F2
    res2 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-REJ-001", from_stage="F2", to_stage="F3", quantity_moved=80, rejected_quantity=5, defect_code="DEF-DIM-OUT"
    ))
    assert res2.success is True
    assert res2.to_stage_available_wip == 80

    # Verify stage rejections are isolated
    wips = {w.stage: w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
    assert wips["F1"].rejected_qty == 15
    assert wips["F2"].rejected_qty == 5
    assert wips["F3"].rejected_qty == 0

    # Verify separate NC records
    ncs = db.query(NCRecord).filter(NCRecord.work_order_id == wo.id).all()
    assert len(ncs) == 2
    assert any(n.stage == "F1" and n.qty == 15 for n in ncs)
    assert any(n.stage == "F2" and n.qty == 5 for n in ncs)


# =========================================================================
# 4. QUANTITY VALIDATION, CROSS-WO & STAGE JUMPING PROTECTION
# =========================================================================

def test_movement_validation_and_cross_wo_protection(db):
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(oar_number="OAR-VAL-01", customer_id=cust.id, part_id=part.id, customer_po="PO-V1", po_qty=50, max_batch_size=50, status=OrderStatus.ACCEPT)
    db.add(order)
    db.commit()

    wo = WorkOrder(wo_number="WO-VAL-001", order_id=order.id, physical_wo_qty=50, current_stage="F1", status=WOStatus.RELEASED)
    db.add(wo)
    db.commit()

    for seq, stg in enumerate(["F1", "F2", "F3", "FI", "PACKING", "DISPATCH"], start=1):
        db.add(WORoute(work_order_id=wo.id, stage=stg, sequence=seq, stage_target_qty=50))
        db.add(StageWIP(work_order_id=wo.id, stage=stg, ent_qty=50 if seq == 1 else 0, ok_qty=0, inproc_qty=50 if seq == 1 else 0, onhand_qty=0, rejected_qty=0, available_wip=50 if seq == 1 else 0))
    db.commit()

    # 1. Over-quantity movement rejection (try 60 > 50)
    with pytest.raises(HTTPException) as exc1:
        ProductionService.move_parts(db, MovePartsRequest(
            wo_number="WO-VAL-001", from_stage="F1", to_stage="F2", quantity_moved=60
        ))
    assert exc1.value.status_code == 400

    # 2. Stage jumping rejection (F1 -> FI directly)
    with pytest.raises(HTTPException) as exc2:
        ProductionService.move_parts(db, MovePartsRequest(
            wo_number="WO-VAL-001", from_stage="F1", to_stage="FI", quantity_moved=20
        ))
    assert exc2.value.status_code == 400

    # 3. Invalid / unknown stage rejection
    with pytest.raises(HTTPException) as exc3:
        ProductionService.move_parts(db, MovePartsRequest(
            wo_number="WO-VAL-001", from_stage="F1", to_stage="UNKNOWN_STAGE", quantity_moved=10
        ))
    assert exc3.value.status_code == 400


# =========================================================================
# 5. IDEMPOTENCY & DUPLICATE REQUEST PROTECTION
# =========================================================================

def test_idempotency_duplicate_protection(db):
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(oar_number="OAR-IDEM-01", customer_id=cust.id, part_id=part.id, customer_po="PO-ID", po_qty=100, max_batch_size=100, status=OrderStatus.ACCEPT)
    db.add(order)
    db.commit()

    wo = WorkOrder(wo_number="WO-IDEM-001", order_id=order.id, physical_wo_qty=100, current_stage="F1", status=WOStatus.RELEASED)
    db.add(wo)
    db.commit()

    for seq, stg in enumerate(["F1", "F2", "FI", "PACKING", "DISPATCH"], start=1):
        db.add(WORoute(work_order_id=wo.id, stage=stg, sequence=seq, stage_target_qty=100))
        db.add(StageWIP(work_order_id=wo.id, stage=stg, ent_qty=100 if seq == 1 else 0, ok_qty=0, inproc_qty=100 if seq == 1 else 0, onhand_qty=0, rejected_qty=0, available_wip=100 if seq == 1 else 0))
    db.commit()

    # First request
    req = MovePartsRequest(
        wo_number="WO-IDEM-001", from_stage="F1", to_stage="F2", quantity_moved=40, client_request_id="TOKEN-ABC-123"
    )
    res1 = ProductionService.move_parts(db, req)
    assert res1.available_wip_remaining == 60
    assert res1.to_stage_available_wip == 40

    # Repeated request with same idempotency token (simulating double click)
    res2 = ProductionService.move_parts(db, req)
    assert res2.movement_id == res1.movement_id
    assert res2.available_wip_remaining == 60  # No double deduction!


# =========================================================================
# 6. PART 41: EXACT BUSINESS SCENARIO COMPLETE TEST
# =========================================================================

def test_part_41_exact_business_scenario(db):
    """
    Simulates the exact business scenario from Part 41:
    - WO Qty = 100
    - Route: F1 -> F2 -> F3 -> SP -> FI -> PACKING -> BSR -> DISPATCH
    - F1: 100 available. Move 50 -> F2 (F1 remaining = 50).
    - Later: Move 50 -> F2 (F1 transferable remaining = 0).
    - F2: Process 50 OK.
    - Later: Process 40 OK + 10 Reject.
    - Therefore: F2 OK = 90, F2 Reject = 10.
    - Forward good quantity = 90 (10 rejection does NOT move forward).
    - Proceed along route: F3 -> SP -> FI -> PACKING -> BSR -> DISPATCH.
    - Test Packing, BSR, Dispatch, and 100% Conservation of Mass.
    """
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    # 1. Create OAR & Work Order
    order = Order(
        oar_number="OAR-SCENARIO-41",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-SCENARIO-41",
        po_qty=100,
        max_batch_size=100,
        delivery_date=date.today() + timedelta(days=14),
        status=OrderStatus.ACCEPT
    )
    db.add(order)
    db.commit()

    wo = WorkOrder(
        wo_number="WO-SCENARIO-41",
        order_id=order.id,
        physical_wo_qty=100,
        current_stage="F1",
        projected_final_good=100,
        shortfall="No",
        status=WOStatus.RELEASED
    )
    db.add(wo)
    db.commit()

    # 2. Dynamic Route: F1 -> F2 -> F3 -> SP -> FI -> PACKING -> BSR -> DISPATCH
    full_route = ["F1", "F2", "F3", "SP", "FI", "PACKING", "BSR", "DISPATCH"]
    for seq, stg in enumerate(full_route, start=1):
        db.add(WORoute(work_order_id=wo.id, stage=stg, sequence=seq, stage_target_qty=100, cumulative_ent_qty=100 if seq == 1 else 0))
        db.add(StageWIP(
            work_order_id=wo.id, stage=stg, ent_qty=100 if seq == 1 else 0, ok_qty=0,
            inproc_qty=100 if seq == 1 else 0, onhand_qty=0, rejected_qty=0,
            available_wip=100 if seq == 1 else 0
        ))
    db.commit()

    # 3. F1: Move 50 -> F2
    t1 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-SCENARIO-41", from_stage="F1", to_stage="F2", quantity_moved=50, client_request_id="SCENARIO-T1"
    ))
    assert t1.success is True
    assert t1.available_wip_remaining == 50
    assert t1.to_stage_available_wip == 50

    # 4. F1: Move another 50 -> F2
    t2 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-SCENARIO-41", from_stage="F1", to_stage="F2", quantity_moved=50, client_request_id="SCENARIO-T2"
    ))
    assert t2.success is True
    assert t2.available_wip_remaining == 0
    assert t2.to_stage_available_wip == 100

    # 5. F2: Process 50 OK and Move to F3
    t3 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-SCENARIO-41", from_stage="F2", to_stage="F3", quantity_moved=50, client_request_id="SCENARIO-T3"
    ))
    assert t3.success is True
    assert t3.available_wip_remaining == 50
    assert t3.to_stage_available_wip == 50

    # 6. F2: Process remaining 50 with 40 OK and 10 Reject
    t4 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-SCENARIO-41", from_stage="F2", to_stage="F3", quantity_moved=40, rejected_quantity=10,
        defect_code="DEF-POROSITY", remarks="F2 machining defect", client_request_id="SCENARIO-T4"
    ))
    assert t4.success is True
    assert t4.available_wip_remaining == 0
    assert t4.to_stage_available_wip == 90  # 50 + 40 = 90 OK pieces at F3!

    # 7. Verify F2 stage results: F2 OK = 90, F2 Reject = 10
    f2_wip = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == "F2").first()
    assert f2_wip.ok_qty == 90
    assert f2_wip.rejected_qty == 10
    assert f2_wip.available_wip == 0

    # 8. F3 -> SP: Move 90
    t5 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-SCENARIO-41", from_stage="F3", to_stage="SP", quantity_moved=90, client_request_id="SCENARIO-T5"
    ))
    assert t5.success is True

    # 9. SP -> FI: Move 90
    t6 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-SCENARIO-41", from_stage="SP", to_stage="FI", quantity_moved=90, client_request_id="SCENARIO-T6"
    ))
    assert t6.success is True

    # 10. FI -> PACKING: Move 90
    t7 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-SCENARIO-41", from_stage="FI", to_stage="PACKING", quantity_moved=90, client_request_id="SCENARIO-T7"
    ))
    assert t7.success is True

    # 11. PACKING: Pack 90 pieces
    pack_res = PackingService.update_packing(db, PackingUpdateRequest(
        wo_number="WO-SCENARIO-41", packed_quantity=90, box_count=2, package_type="VCI Crates"
    ))
    assert pack_res.ready_for_dispatch == 90

    # 12. PACKING -> BSR: Move 90
    t8 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-SCENARIO-41", from_stage="PACKING", to_stage="BSR", quantity_moved=90, client_request_id="SCENARIO-T8"
    ))
    assert t8.success is True

    # 13. BSR -> DISPATCH: Dispatch 90 pieces
    disp_res = DispatchService.execute_dispatch(db, DispatchRequest(
        wo_number="WO-SCENARIO-41", invoice_number="INV-SCENARIO-41", dispatched_quantity=90, customer_po="PO-SCENARIO-41"
    ))
    assert disp_res.success is True
    assert disp_res.dispatched_quantity == 90
    assert disp_res.wo_status == "dispatched"

    # 14. 100% Conservation of Mass / Plant Reconciliation
    recon = OMSIntegrationService.reconcile_work_order(db, wo)
    assert recon.released_qty == 100
    assert recon.total_rejected == 10
    assert recon.dispatched_qty == 90
    assert recon.total_wip == 0
    assert recon.variance == 0
    assert recon.is_balanced is True


# =========================================================================
# 7. PHASE 1: CROSS-WO REJECTION TEST (STEP 4)
# =========================================================================

def test_cross_wo_movement_rejected(db):
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(oar_number="OAR-XWO-01", customer_id=cust.id, part_id=part.id, customer_po="PO-XWO", po_qty=100, max_batch_size=50, status=OrderStatus.ACCEPT)
    db.add(order)
    db.commit()

    wo_a = WorkOrder(wo_number="WO-A-001", order_id=order.id, physical_wo_qty=50, current_stage="F1", status=WOStatus.RELEASED)
    wo_b = WorkOrder(wo_number="WO-B-002", order_id=order.id, physical_wo_qty=50, current_stage="F1", status=WOStatus.RELEASED)
    db.add_all([wo_a, wo_b])
    db.commit()

    OMSIntegrationService.initialize_wo_stages(db, wo_a, "F1 > F2 > FI > PACKING > DISPATCH")
    OMSIntegrationService.initialize_wo_stages(db, wo_b, "F1 > F2 > FI > PACKING > DISPATCH")
    db.commit()

    # Attempt cross-WO movement from WO-A to WO-B
    with pytest.raises(HTTPException) as exc:
        ProductionService.move_parts(db, MovePartsRequest(
            wo_number="WO-A-001",
            target_wo_number="WO-B-002",
            from_stage="F1",
            to_stage="F2",
            quantity_moved=10
        ))
    assert exc.value.status_code == 400
    assert "Stage movement cannot cross Work Orders." in exc.value.detail


# =========================================================================
# 8. PHASE 1: DYNAMIC NEXT STAGE RESOLUTION (STEP 3)
# =========================================================================

def test_dynamic_get_next_stage(db):
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(oar_number="OAR-DNS-01", customer_id=cust.id, part_id=part.id, customer_po="PO-DNS", po_qty=100, max_batch_size=100, status=OrderStatus.ACCEPT)
    db.add(order)
    db.commit()

    # WO 1: FI -> BSR -> DISPATCH
    wo1 = WorkOrder(wo_number="WO-DNS-01", order_id=order.id, physical_wo_qty=100, current_stage="F1", status=WOStatus.RELEASED)
    db.add(wo1)
    db.commit()
    OMSIntegrationService.initialize_wo_stages(db, wo1, "F1 > F2 > SP > FI > BSR > DISPATCH")

    assert OMSIntegrationService.get_next_stage(db, wo1, "F1") == "F2"
    assert OMSIntegrationService.get_next_stage(db, wo1, "F2") == "SP"
    assert OMSIntegrationService.get_next_stage(db, wo1, "SP") == "FI"
    assert OMSIntegrationService.get_next_stage(db, wo1, "FI") == "BSR"
    assert OMSIntegrationService.get_next_stage(db, wo1, "BSR") == "DISPATCH"
    assert OMSIntegrationService.get_next_stage(db, wo1, "DISPATCH") is None

    # WO 2: FI -> PACKING -> BSR -> DISPATCH
    wo2 = WorkOrder(wo_number="WO-DNS-02", order_id=order.id, physical_wo_qty=100, current_stage="F1", status=WOStatus.RELEASED)
    db.add(wo2)
    db.commit()
    OMSIntegrationService.initialize_wo_stages(db, wo2, "F1 > F2 > F3 > SP > FI > PACKING > BSR > DISPATCH")

    assert OMSIntegrationService.get_next_stage(db, wo2, "FI") == "PACKING"
    assert OMSIntegrationService.get_next_stage(db, wo2, "PACKING") == "BSR"
    assert OMSIntegrationService.get_next_stage(db, wo2, "BSR") == "DISPATCH"


# =========================================================================
# 9. PHASE 1: AUTHORITATIVE LIVE STAGE STATE (STEP 11)
# =========================================================================

def test_authoritative_get_current_stage_state(db):
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(oar_number="OAR-STA-01", customer_id=cust.id, part_id=part.id, customer_po="PO-STA", po_qty=100, max_batch_size=100, status=OrderStatus.ACCEPT)
    db.add(order)
    db.commit()

    wo = WorkOrder(wo_number="WO-STA-001", order_id=order.id, physical_wo_qty=100, current_stage="F1", status=WOStatus.RELEASED)
    db.add(wo)
    db.commit()

    OMSIntegrationService.initialize_wo_stages(db, wo, "F1 > F2 > FI > PACKING > DISPATCH")
    db.commit()

    # Move 40 to F2, reject 10 at F1
    ProductionService.move_parts(db, MovePartsRequest(
        wo_number="WO-STA-001", from_stage="F1", to_stage="F2", quantity_moved=40, rejected_quantity=10,
        defect_code="DEF-POROSITY"
    ))

    # Check F1 state
    f1_state = OMSIntegrationService.get_current_stage_state(db, wo, "F1")
    assert f1_state["ok_completed_qty"] == 40
    assert f1_state["rejected_qty"] == 10
    assert f1_state["in_process_qty"] == 50  # 100 - 40 - 10 = 50
    assert f1_state["on_hand_qty"] == 0      # 40 OK - 40 Ent(next) = 0
    assert f1_state["available_wip"] == 50
    assert f1_state["next_stage"] == "F2"

    # Check F2 state
    f2_state = OMSIntegrationService.get_current_stage_state(db, wo, "F2")
    assert f2_state["available_wip"] == 40
    assert f2_state["in_process_qty"] == 40
    assert f2_state["ok_completed_qty"] == 0
    assert f2_state["next_stage"] == "FI"


# =========================================================================
# 10. PHASE 1: ATOMIC STAGE INITIALIZATION (STEP 21)
# =========================================================================

def test_atomic_stage_initialization(db):
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(oar_number="OAR-ATM-01", customer_id=cust.id, part_id=part.id, customer_po="PO-ATM", po_qty=80, max_batch_size=80, status=OrderStatus.ACCEPT)
    db.add(order)
    db.commit()

    wo = WorkOrder(wo_number="WO-ATM-001", order_id=order.id, physical_wo_qty=80, current_stage="F1", status=WOStatus.RELEASED)
    db.add(wo)
    db.commit()

    routes = OMSIntegrationService.initialize_wo_stages(db, wo, "F1 > F2 > SP > FI > PACKING > DISPATCH")
    assert len(routes) == 6
    assert [r.stage for r in routes] == ["F1", "F2", "SP", "FI", "PACKING", "DISPATCH"]

    # Verify StageWIP records created simultaneously
    wips = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
    assert len(wips) == 6
    assert wips[0].ent_qty == 80
    assert wips[0].available_wip == 80
    assert all(w.ok_qty == 0 for w in wips)
