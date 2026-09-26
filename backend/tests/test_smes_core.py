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
from app.schemas.operations import OrderIntakeCreate, WOReleaseCreate
from app.models.work_order import WorkOrder
from fastapi import HTTPException

# Test with in-memory SQLite database
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

def test_initial_seeding(db_session):
    wos = db_session.query(WorkOrder).all()
    assert len(wos) >= 5
    wo1 = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-1001").first()
    assert wo1 is not None
    assert wo1.current_stage == "F2"

def test_partial_movement_updates_wip(db_session):
    # WO-1001 is at F2 with 480 available pieces
    req = MovePartsRequest(
        wo_number="WO-1001",
        from_stage="F2",
        to_stage="F3",
        quantity_moved=200,
        rejected_quantity=5,
        defect_code="DEF-POROSITY",
        machine_id="M-LATHE-01",
        operator_name="Operator Test",
        shift="Shift A"
    )
    res = ProductionService.move_parts(db_session, req)
    assert res.success is True
    assert res.quantity_moved == 200
    assert res.rejected_quantity == 5
    assert res.available_wip_remaining == 480 - 205  # 275
    assert res.to_stage_available_wip == 200

def test_over_movement_blocked(db_session):
    # Available at F2 is 480. Attempt to move 600 pieces.
    req = MovePartsRequest(
        wo_number="WO-1001",
        from_stage="F2",
        to_stage="F3",
        quantity_moved=600,
        rejected_quantity=0
    )
    with pytest.raises(HTTPException) as excinfo:
        ProductionService.move_parts(db_session, req)
    assert excinfo.value.status_code == 400
    assert "Only" in excinfo.value.detail

def test_invalid_stage_sequence_blocked(db_session):
    # Attempt to jump from F2 directly to DISPATCH or FI
    req = MovePartsRequest(
        wo_number="WO-1001",
        from_stage="F2",
        to_stage="DISPATCH",
        quantity_moved=100,
        rejected_quantity=0
    )
    with pytest.raises(HTTPException) as excinfo:
        ProductionService.move_parts(db_session, req)
    assert excinfo.value.status_code == 400
    assert "Invalid stage sequence" in excinfo.value.detail

def test_packing_and_dispatch_flow(db_session):
    # WO-1006 is at PACKING stage: 200 packed (ready for dispatch), 95 pending packing
    # 1. Pack additional 50 pieces
    pack_req = PackingUpdateRequest(
        wo_number="WO-1006",
        packed_quantity=50,
        box_count=2
    )
    pack_res = PackingService.update_packing(db_session, pack_req)
    assert pack_res.success is True
    assert pack_res.packed_this_batch == 50
    assert pack_res.total_packed == 250
    assert pack_res.remaining_pending == 45
    assert pack_res.ready_for_dispatch == 250

    # 2. Dispatch validation: Attempt to dispatch 300 pieces (when only 250 are ready) -> Must be blocked!
    disp_over_req = DispatchRequest(
        wo_number="WO-1006",
        invoice_number="INV-TEST-999",
        dispatched_quantity=300
    )
    with pytest.raises(HTTPException) as excinfo:
        DispatchService.execute_dispatch(db_session, disp_over_req)
    assert excinfo.value.status_code == 400
    assert "Only 250 pieces are ready for dispatch" in excinfo.value.detail

    # 3. Valid Dispatch: Dispatch 200 pieces
    disp_valid_req = DispatchRequest(
        wo_number="WO-1006",
        invoice_number="INV-TEST-001",
        dispatched_quantity=200,
        vehicle_number="KA-01-AB-1234"
    )
    disp_res = DispatchService.execute_dispatch(db_session, disp_valid_req)
    assert disp_res.success is True
    assert disp_res.dispatched_quantity == 200
    assert disp_res.remaining_ready_for_dispatch == 50

def test_order_intake_creates_wos(db_session):
    req = OrderIntakeCreate(
        customer_code="CUST-NEW",
        customer_name="New Engineering Ltd",
        customer_po="PO-NEW-101",
        part_number="BRZ-TEST-99",
        po_quantity=1000,
        max_batch_size=500
    )
    res = OperationsService.create_order_intake(db_session, req)
    assert res.success is True
    assert len(res.wos_created) == 2
    assert res.total_qty == 1000
