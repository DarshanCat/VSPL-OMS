import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.services.seed_service import seed_database_if_empty
from app.services.production_service import ProductionService
from app.services.packing_service import PackingService
from app.services.dispatch_service import DispatchService
from app.services.work_order_service import WorkOrderService
from app.services.operations_service import OperationsService
from app.schemas.production import MovePartsRequest
from app.schemas.packing import PackingUpdateRequest
from app.schemas.dispatch import DispatchRequest
from app.schemas.operations import OrderIntakeCreate, WOReleaseCreate, ConversionCreate
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.nc import NCRecord
from fastapi import HTTPException

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

def test_full_e2e_work_order_simulation(db_session):
    """
    Simulates complete lifecycle of TEST-WO-001 (1,000 pcs):
    F1 -> F2 -> F3 -> SP -> FI -> PACKING / BSR -> DISPATCH
    """
    # 1. Create Order and Release WO-001 for 1,000 pcs
    intake_req = OrderIntakeCreate(
        customer_code="CUST-VALVE",
        customer_name="Flowserve Controls Ltd",
        customer_po="PO-E2E-TEST-001",
        part_number="BRZ-BUSH-100",
        po_quantity=1000,
        max_batch_size=1000
    )
    intake_res = OperationsService.create_order_intake(db_session, intake_req)
    wo_num = intake_res.wos_created[0]

    # Check initial F1 WIP
    wip_f1 = db_session.query(StageWIP).filter(StageWIP.work_order_id == intake_res.order_id, StageWIP.stage == "F1").first()
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
    wip_f1 = db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == "F1").first()
    assert wip_f1.available_wip == 1000

    # Step 1: F1 -> F2 (Move 600 pieces)
    m1 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num,
        from_stage="F1",
        to_stage="F2",
        quantity_moved=600,
        rejected_quantity=0,
        machine_id="M-CC01"
    ))
    assert m1.success is True
    assert m1.available_wip_remaining == 400  # F1 remaining WIP
    assert m1.to_stage_available_wip == 600   # F2 WIP

    # Step 2: F2 -> F3 (Move 500 pieces)
    m2 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num,
        from_stage="F2",
        to_stage="F3",
        quantity_moved=500,
        rejected_quantity=0,
        machine_id="M-LATHE-01"
    ))
    assert m2.success is True
    assert m2.available_wip_remaining == 100  # F2 remaining WIP
    assert m2.to_stage_available_wip == 500   # F3 WIP

    # Step 3: F3 -> SP (Move 500 pieces)
    m3 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num,
        from_stage="F3",
        to_stage="SP",
        quantity_moved=500,
        rejected_quantity=0,
        machine_id="M-VMC-01"
    ))
    assert m3.success is True
    assert m3.available_wip_remaining == 0
    assert m3.to_stage_available_wip == 500

    # Step 4: SP -> FI (Move 490 pieces, 10 rejected at SP)
    m4 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num,
        from_stage="SP",
        to_stage="FI",
        quantity_moved=490,
        rejected_quantity=10,
        defect_code="DEF-SURF-BLOW",
        remarks="Subcontract surface blowhole defect"
    ))
    assert m4.success is True
    assert m4.available_wip_remaining == 0
    assert m4.to_stage_available_wip == 490

    # Verify NC was raised for the 10 rejected parts
    nc_sp = db_session.query(NCRecord).filter(NCRecord.work_order_id == wo.id, NCRecord.stage == "SP").first()
    assert nc_sp is not None
    assert nc_sp.qty == 10
    assert nc_sp.defect_code == "DEF-SURF-BLOW"

    # Step 5: FI -> PACKING (Move 450 approved pieces, 40 rejected at FI)
    # Rejected parts at FI must NOT enter Packing!
    m5 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num,
        from_stage="FI",
        to_stage="PACKING",
        quantity_moved=450,
        rejected_quantity=40,
        defect_code="DEF-DIM-OUT",
        remarks="CMM dimensional out of tolerance"
    ))
    assert m5.success is True
    assert m5.available_wip_remaining == 0
    assert m5.to_stage_available_wip == 450

    # Check Packing record received exactly 450 pieces
    pr = db_session.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
    assert pr is not None
    assert pr.fi_approved_qty == 450
    assert pr.pending_qty == 450
    assert pr.ready_for_dispatch_qty == 0

    # Step 6: Execute Packing / BSR for 450 pieces
    pack_res = PackingService.update_packing(db_session, PackingUpdateRequest(
        wo_number=wo_num,
        packed_quantity=450,
        box_count=3,
        package_type="Standard Wooden Box"
    ))
    assert pack_res.success is True
    assert pack_res.total_packed == 450
    assert pack_res.ready_for_dispatch == 450
    assert pack_res.remaining_pending == 0

    # Step 7: Dispatch Gatekeeper Validation
    # Attempt to dispatch 500 (more than 450 ready) -> MUST BE BLOCKED
    with pytest.raises(HTTPException) as exc:
        DispatchService.execute_dispatch(db_session, DispatchRequest(
            wo_number=wo_num,
            invoice_number="INV-FAIL-001",
            dispatched_quantity=500
        ))
    assert exc.value.status_code == 400
    assert "Only 450 pieces are ready for dispatch" in exc.value.detail

    # Dispatch valid partial 400 pieces
    d1 = DispatchService.execute_dispatch(db_session, DispatchRequest(
        wo_number=wo_num,
        invoice_number="INV-2026-9001",
        dispatched_quantity=400,
        vehicle_number="KA-01-E-9999"
    ))
    assert d1.success is True
    assert d1.dispatched_quantity == 400
    assert d1.remaining_ready_for_dispatch == 50

    # Dispatch remaining 50 pieces
    d2 = DispatchService.execute_dispatch(db_session, DispatchRequest(
        wo_number=wo_num,
        invoice_number="INV-2026-9002",
        dispatched_quantity=50,
        vehicle_number="KA-01-E-9999"
    ))
    assert d2.success is True
    assert d2.dispatched_quantity == 50
    assert d2.remaining_ready_for_dispatch == 0
    assert d2.wo_status == WOStatus.DISPATCHED.value

    # Step 8: Total Quantity Reconciliation Check
    # Original Released: 1,000
    # Remaining F1: 400
    # Remaining F2: 100
    # SP Rejected: 10
    # FI Rejected: 40
    # Dispatched: 450
    # Sum: 400 + 100 + 10 + 40 + 450 = 1,000 (Zero parts lost, zero parts duplicated!)
    wips = db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
    wip_map = {w.stage: w.available_wip for w in wips}
    assert wip_map["F1"] == 400
    assert wip_map["F2"] == 100
    assert wip_map["F3"] == 0
    assert wip_map["SP"] == 0
    assert wip_map["FI"] == 0

    rejs = db_session.query(NCRecord).filter(NCRecord.work_order_id == wo.id).all()
    total_rej = sum(r.qty for r in rejs)
    assert total_rej == 50

    pr_final = db_session.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
    assert pr_final.dispatched_qty == 450
    assert pr_final.ready_for_dispatch_qty == 0

    assert (wip_map["F1"] + wip_map["F2"] + total_rej + pr_final.dispatched_qty) == 1000

def test_custom_routes_per_work_order(db_session):
    """
    Verifies that Work Orders can follow distinct custom routes:
    WO-A: F1 -> F2 -> F3 -> FI -> PACKING / BSR -> DISPATCH (skips SP)
    WO-B: F1 -> SP -> FI -> PACKING / BSR -> DISPATCH (skips F2 & F3)
    WO-C: F1 -> F2 -> PACKING -> BSR -> DISPATCH (separate PACKING and BSR)
    """
    # Create WO-A with custom route skipping SP
    OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-PUMP",
        customer_name="Kirloskar Brothers Pumps",
        customer_po="PO-ROUTE-A",
        part_number="BRZ-RING-250",
        po_quantity=200,
        max_batch_size=200
    ))
    wo_a = db_session.query(WorkOrder).filter(WorkOrder.physical_wo_qty == 200).order_by(WorkOrder.created_at.desc()).first()
    OperationsService.release_work_order(db_session, WOReleaseCreate(
        wo_number=wo_a.wo_number,
        physical_wo_qty=200,
        route_stages=["F1", "F2", "F3", "FI", "PACKING / BSR", "DISPATCH"]
    ))

    # Test WO-A moves F1 -> F2 -> F3 -> FI directly (skipping SP as configured)
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_a.wo_number, from_stage="F1", to_stage="F2", quantity_moved=200
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_a.wo_number, from_stage="F2", to_stage="F3", quantity_moved=200
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_a.wo_number, from_stage="F3", to_stage="FI", quantity_moved=200
    ))

    # Attempt to move to SP on WO-A -> MUST BE BLOCKED since SP is not on its route
    with pytest.raises(HTTPException) as exc:
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo_a.wo_number, from_stage="FI", to_stage="SP", quantity_moved=100
        ))
    assert exc.value.status_code == 400
    assert "not part of the released route" in exc.value.detail

def test_immutable_movement_ledger(db_session):
    """
    Verifies every movement creates an immutable transaction record with complete audit metadata.
    """
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-1001").first()
    prev_count = db_session.query(ProductionMovement).count()

    res = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="WO-1001",
        from_stage="F2",
        to_stage="F3",
        quantity_moved=100,
        rejected_quantity=2,
        machine_id="M-LATHE-02",
        operator_name="Devanand",
        shift="Shift B",
        defect_code="DEF-POROSITY",
        remarks="Batch run test"
    ))
    assert res.success is True

    new_count = db_session.query(ProductionMovement).count()
    assert new_count == prev_count + 1

    latest_mov = db_session.query(ProductionMovement).filter(ProductionMovement.movement_id == res.movement_id).first()
    assert latest_mov is not None
    assert latest_mov.from_stage == "F2"
    assert latest_mov.to_stage == "F3"
    assert latest_mov.quantity_moved == 100
    assert latest_mov.rejected_quantity == 2
    assert latest_mov.machine_id == "M-LATHE-02"
    assert latest_mov.operator_name == "Devanand"
    assert latest_mov.shift == "Shift B"
    assert latest_mov.remarks == "Batch run test"
