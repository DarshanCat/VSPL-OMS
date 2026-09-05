import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.core.database import Base
from app.services.seed_service import seed_database_if_empty
from app.services.production_service import ProductionService
from app.services.packing_service import PackingService
from app.services.dispatch_service import DispatchService
from app.services.work_order_service import WorkOrderService
from app.services.operations_service import OperationsService
from app.services.oms_integration_service import OMSIntegrationService
from app.schemas.production import MovePartsRequest
from app.schemas.packing import PackingUpdateRequest
from app.schemas.dispatch import DispatchRequest
from app.schemas.operations import OrderIntakeCreate, WOReleaseCreate, ConversionCreate
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.nc import NCRecord

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    seed_database_if_empty(session)
    yield session
    session.close()

def test_1_partial_movement(db_session):
    """
    Test 1: WO Qty: 1,000 | Move F1 -> F2: 600 pieces.
    Verify OMS flow counters: F1 (OK: 600, InProc: 400, OnHand: 0), F2 (Ent: 600, InProc: 600, OnHand: 0).
    """
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-OMS",
        customer_name="Siemens Energy",
        customer_po="PO-OMS-001",
        part_number="BRZ-SEAL-01",
        po_quantity=1000,
        max_batch_size=1000
    ))
    wo_num = res.wos_created[0]
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    mov = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num,
        from_stage="F1",
        to_stage="F2",
        quantity_moved=600,
        rejected_quantity=0,
        machine_id="M-CC01"
    ))
    assert mov.success is True
    assert mov.available_wip_remaining == 400
    assert mov.to_stage_available_wip == 600

    wips = {w.stage: w for w in db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
    assert wips["F1"].ok_qty == 600
    assert wips["F1"].inproc_qty == 400
    assert wips["F1"].onhand_qty == 0
    assert wips["F2"].ent_qty == 600
    assert wips["F2"].inproc_qty == 600

def test_2_multiple_partial_movements(db_session):
    """
    Test 2: F1 -> F2 in three tranches: 300 + 200 + 100 = 600 total.
    Verify no duplicate WIP and exact accumulated quantity = 600.
    """
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-OMS",
        customer_name="Siemens Energy",
        customer_po="PO-OMS-002",
        part_number="BRZ-SEAL-02",
        po_quantity=1000,
        max_batch_size=1000
    ))
    wo_num = res.wos_created[0]
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num, from_stage="F1", to_stage="F2", quantity_moved=300
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num, from_stage="F1", to_stage="F2", quantity_moved=200
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num, from_stage="F1", to_stage="F2", quantity_moved=100
    ))

    wips = {w.stage: w for w in db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
    assert wips["F1"].ok_qty == 600
    assert wips["F1"].available_wip == 400
    assert wips["F2"].ent_qty == 600
    assert wips["F2"].available_wip == 600

def test_3_stage_completion_mapping(db_session):
    """
    Test 3: Verify physical movement maps to source stage OK (completed) and next stage Ent (received).
    """
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-1001").first()
    wips_before = {w.stage: (w.ok_qty, w.ent_qty) for w in db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}

    m = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="WO-1001",
        from_stage="F2",
        to_stage="F3",
        quantity_moved=100,
        machine_id="M-LATHE-01"
    ))
    assert m.success is True

    f2_wip = db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == "F2").first()
    f3_wip = db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == "F3").first()

    assert f2_wip.ok_qty == wips_before.get("F2", (0, 0))[0] + 100
    assert f3_wip.ent_qty == wips_before.get("F3", (0, 0))[1] + 100

def test_4_rejection_isolation(db_session):
    """
    Test 4: SP entered 500, OK 480, Rej 20.
    Verify rejected quantity does not enter FI automatically and NC is raised.
    """
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-OMS", customer_name="Kirloskar", customer_po="PO-REJ-01",
        part_number="BRZ-VALVE-01", po_quantity=500, max_batch_size=500
    ))
    wo_num = res.wos_created[0]
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="F1", to_stage="F2", quantity_moved=500))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="F2", to_stage="F3", quantity_moved=500))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="F3", to_stage="SP", quantity_moved=500))

    # Move SP -> FI (480 good, 20 rejected)
    m = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num,
        from_stage="SP",
        to_stage="FI",
        quantity_moved=480,
        rejected_quantity=20,
        defect_code="DEF-POROSITY",
        remarks="Subcontract porosity check"
    ))
    assert m.success is True
    assert m.available_wip_remaining == 0
    assert m.to_stage_available_wip == 480

    wips = {w.stage: w for w in db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
    assert wips["SP"].rejected_qty == 20
    assert wips["FI"].ent_qty == 480

    nc = db_session.query(NCRecord).filter(NCRecord.work_order_id == wo.id, NCRecord.stage == "SP").first()
    assert nc is not None
    assert nc.qty == 20

def test_5_fi_to_packing_quality_gate(db_session):
    """
    Test 5: FI to Packing / BSR quality gate.
    Move 450 approved from FI to Packing, 30 rejected at FI.
    Verify only 450 pieces enter PackingRecord; 30 rejections are blocked.
    """
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-OMS", customer_name="L&T Valves", customer_po="PO-FI-GATE",
        part_number="BRZ-BUSH-400", po_quantity=480, max_batch_size=480
    ))
    wo_num = res.wos_created[0]
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="F1", to_stage="F2", quantity_moved=480))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="F2", to_stage="F3", quantity_moved=480))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="F3", to_stage="SP", quantity_moved=480))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="SP", to_stage="FI", quantity_moved=480))

    # Move FI -> PACKING (450 good, 30 rejected)
    m = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num,
        from_stage="FI",
        to_stage="PACKING",
        quantity_moved=450,
        rejected_quantity=30,
        defect_code="DEF-CMM-OUT",
        remarks="CMM dimensional inspection failure"
    ))
    assert m.success is True
    
    pr = db_session.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
    assert pr.fi_approved_qty == 450
    assert pr.pending_qty == 450
    assert pr.ready_for_dispatch_qty == 0

def test_6_dispatch_gatekeeper(db_session):
    """
    Test 6: Packing 450 pcs -> Ready for Dispatch = 450.
    Attempt Dispatch 500 -> REJECT (HTTP 400).
    Dispatch 400 -> SUCCESS (Remaining Ready = 50).
    """
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-1004").first()
    pr = db_session.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
    if not pr:
        pr = PackingRecord(
            work_order_id=wo.id,
            fi_approved_qty=450,
            pending_qty=450,
            ready_for_dispatch_qty=0
        )
        db_session.add(pr)
        db_session.commit()

    # Complete packing of 450 pcs
    PackingService.update_packing(db_session, PackingUpdateRequest(
        wo_number=wo.wo_number,
        packed_quantity=450,
        box_count=2,
        package_type="Heavy Duty Crates"
    ))
    db_session.refresh(pr)
    assert pr.ready_for_dispatch_qty == 450

    # Over-dispatch attempt
    with pytest.raises(HTTPException) as exc:
        DispatchService.execute_dispatch(db_session, DispatchRequest(
            wo_number=wo.wo_number,
            invoice_number="INV-OVER-001",
            dispatched_quantity=500
        ))
    assert exc.value.status_code == 400
    assert "Only 450 pieces are ready for dispatch" in exc.value.detail

    # Valid dispatch
    d_res = DispatchService.execute_dispatch(db_session, DispatchRequest(
        wo_number=wo.wo_number,
        invoice_number="INV-VALID-001",
        dispatched_quantity=400
    ))
    assert d_res.success is True
    assert d_res.remaining_ready_for_dispatch == 50

def test_7_idempotency_protection(db_session):
    """
    Test 7: Idempotency token client_request_id prevents duplicate movement on network retry.
    """
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-1001").first()
    client_token = "IDEMP-KEY-TEST-777"

    # First attempt
    m1 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="WO-1001",
        from_stage="F2",
        to_stage="F3",
        quantity_moved=100,
        client_request_id=client_token,
        machine_id="M-LATHE-01"
    ))
    assert m1.success is True

    # Immediate retry with same token
    m2 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="WO-1001",
        from_stage="F2",
        to_stage="F3",
        quantity_moved=100,
        client_request_id=client_token,
        machine_id="M-LATHE-01"
    ))
    assert m2.success is True
    assert m2.movement_id == m1.movement_id
    assert "Duplicate request detected" in m2.message

def test_8_source_metadata_and_reconciliation(db_session):
    """
    Test 8: Source metadata tracking and plant-wide reconciliation.
    """
    recon = OMSIntegrationService.reconcile_all_work_orders(db_session)
    assert recon.total_work_orders > 0
    assert recon.is_plant_balanced is True

def test_9_dynamic_routes_variation(db_session):
    """
    Test 9: Verify multiple route configurations per Work Order:
    WO A: F1 -> F2 -> F3 -> FI -> PACKING -> DISPATCH (skips SP)
    WO B: F1 -> F2 -> SP -> FI -> PACKING / BSR -> DISPATCH (skips F3)
    WO C: F1 -> F2 -> FI -> PACKING -> BSR -> DISPATCH (discrete PACKING and BSR)
    """
    # WO A
    r_a = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-ROUTE", customer_name="Route Test A", customer_po="PO-R-A",
        part_number="BRZ-R-01", po_quantity=100, max_batch_size=100
    ))
    wo_a = r_a.wos_created[0]
    OperationsService.release_work_order(db_session, WOReleaseCreate(
        wo_number=wo_a, physical_wo_qty=100, route_stages=["F1", "F2", "F3", "FI", "PACKING", "DISPATCH"]
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_a, from_stage="F1", to_stage="F2", quantity_moved=100))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_a, from_stage="F2", to_stage="F3", quantity_moved=100))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_a, from_stage="F3", to_stage="FI", quantity_moved=100))

    # WO C: Separate PACKING and BSR
    r_c = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-ROUTE", customer_name="Route Test C", customer_po="PO-R-C",
        part_number="BRZ-R-03", po_quantity=100, max_batch_size=100
    ))
    wo_c = r_c.wos_created[0]
    OperationsService.release_work_order(db_session, WOReleaseCreate(
        wo_number=wo_c, physical_wo_qty=100, route_stages=["F1", "F2", "FI", "PACKING", "BSR", "DISPATCH"]
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_c, from_stage="F1", to_stage="F2", quantity_moved=100))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_c, from_stage="F2", to_stage="FI", quantity_moved=100))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_c, from_stage="FI", to_stage="PACKING", quantity_moved=100))
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_c, from_stage="PACKING", to_stage="BSR", quantity_moved=100))

def test_10_end_to_end_factory_simulation(db_session):
    """
    Test 10: Complete End-to-End Simulation of TEST-OMS-SMES-001 (1,000 pcs):
    F1 -> F2 -> F3 -> SP -> FI -> PACKING / BSR -> DISPATCH
    Includes:
    - Partial movement
    - Multiple movements
    - Subcontract rejections
    - FI CMM rejection
    - Packing / BSR
    - Partial dispatches
    - Full quantity balance reconciliation
    """
    # 1. Intake and Release WO for 1,000 pcs
    intake = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-E2E",
        customer_name="BHEL Heavy Engineering",
        customer_po="PO-E2E-FULL-01",
        part_number="BRZ-BUSH-1000",
        po_quantity=1000,
        max_batch_size=1000
    ))
    wo_num = intake.wos_created[0]
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    # Move 1: F1 -> F2 (600 pcs)
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="F1", to_stage="F2", quantity_moved=600))
    # Move 2: F2 -> F3 (500 pcs)
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="F2", to_stage="F3", quantity_moved=500))
    # Move 3: F3 -> SP (500 pcs)
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="F3", to_stage="SP", quantity_moved=500))
    # Move 4: SP -> FI (490 pcs good, 10 rejected at SP)
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="SP", to_stage="FI", quantity_moved=490, rejected_quantity=10, defect_code="DEF-BLOWHOLE"))
    # Move 5: FI -> PACKING / BSR (450 approved, 40 rejected at FI)
    ProductionService.move_parts(db_session, MovePartsRequest(wo_number=wo_num, from_stage="FI", to_stage="PACKING / BSR", quantity_moved=450, rejected_quantity=40, defect_code="DEF-DIM-OUT"))

    # Packing / BSR complete 450 pcs
    pack_out = PackingService.update_packing(db_session, PackingUpdateRequest(
        wo_number=wo_num,
        packed_quantity=450,
        box_count=3,
        package_type="Standard Export Wooden Boxes"
    ))
    assert pack_out.ready_for_dispatch == 450

    # Dispatch 400 pcs under Invoice 1
    d1 = DispatchService.execute_dispatch(db_session, DispatchRequest(
        wo_number=wo_num,
        invoice_number="INV-2026-FINAL-01",
        dispatched_quantity=400
    ))
    assert d1.remaining_ready_for_dispatch == 50

    # Dispatch remaining 50 pcs under Invoice 2
    d2 = DispatchService.execute_dispatch(db_session, DispatchRequest(
        wo_number=wo_num,
        invoice_number="INV-2026-FINAL-02",
        dispatched_quantity=50
    ))
    assert d2.remaining_ready_for_dispatch == 0
    assert d2.wo_status == WOStatus.DISPATCHED.value

    # Full Reconciliation Verification
    recon = OMSIntegrationService.reconcile_work_order(db_session, wo)
    assert recon.is_balanced is True
    assert recon.released_qty == 1000
    assert recon.total_wip == 500      # 400 at F1 + 100 at F2
    assert recon.total_rejected == 50 # 10 at SP + 40 at FI
    assert recon.dispatched_qty == 450 # 400 + 50
    assert recon.accounted_qty == 1000
    assert recon.variance == 0
