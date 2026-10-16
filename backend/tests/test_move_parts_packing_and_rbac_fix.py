import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.roles import PRODUCTION_ENTRY_ROLES, MATERIAL_MOVEMENT_ROLES
from app.models.user import UserRole, User
from app.models.work_order import WorkOrder
from app.models.production_movement import StageWIP, ProductionMovement
from app.services.seed_service import seed_database_if_empty
from app.services.operations_service import OperationsService
from app.services.production_service import ProductionService, _get_next_movement_id
from app.services.work_order_service import WorkOrderService
from app.schemas.operations import OrderIntakeCreate
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest

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

def _create_test_wo(db, qty=100):
    res = OperationsService.create_order_intake(db, OrderIntakeCreate(
        customer_code=f"CUST-{uuid.uuid4().hex[:6]}",
        customer_name="Test Client",
        customer_po=f"PO-{uuid.uuid4().hex[:8]}",
        part_number=f"PART-{uuid.uuid4().hex[:6]}",
        po_quantity=qty,
        max_batch_size=qty,
        create_wos=True
    ))
    return res.wos_created[0]

def test_rbac_roles_include_planner_sales_and_data_analyst():
    """Verify that Planner, Sales, and Data Analyst roles are authorized to entry production and move parts."""
    assert UserRole.PLANNER in PRODUCTION_ENTRY_ROLES
    assert UserRole.SALES in PRODUCTION_ENTRY_ROLES
    assert UserRole.DATA_ANALYST in PRODUCTION_ENTRY_ROLES

    assert UserRole.PLANNER in MATERIAL_MOVEMENT_ROLES
    assert UserRole.SALES in MATERIAL_MOVEMENT_ROLES
    assert UserRole.DATA_ANALYST in MATERIAL_MOVEMENT_ROLES

def test_next_movement_id_sequential_and_collision_free(db_session):
    """Verify _get_next_movement_id finds the highest movement ID and increments without collision."""
    wo_num = _create_test_wo(db_session, 50)
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    # Create dummy movements with out-of-order IDs
    m1 = ProductionMovement(
        movement_id="MOV-000005",
        work_order_id=wo.id,
        from_stage="F1",
        to_stage="F2",
        quantity_moved=10,
        rejected_quantity=0,
        movement_date="2026-10-16",
        movement_time="10:00:00"
    )
    db_session.add(m1)
    db_session.commit()

    # Even though count is 1, next id should be MOV-000006, not MOV-000002!
    next_id = _get_next_movement_id(db_session)
    assert next_id == "MOV-000006"

def test_packing_bsr_to_dispatch_preserves_onhand_wip(db_session):
    """Test full flow: F1 -> F2 -> F3 -> SP -> FI -> PACKING / BSR -> DISPATCH.
    Verifies that when production is entered at PACKING / BSR, onhand_qty is NOT zeroed out,
    allowing material to be moved to DISPATCH successfully without failing.
    """
    wo_num = _create_test_wo(db_session, 50)
    user = db_session.query(User).filter(User.role == UserRole.ADMIN).first()

    stages = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]

    # Flow 50 pieces step-by-step through all stages
    for i in range(len(stages) - 1):
        stg_from = stages[i]
        stg_to = stages[i + 1]

        # 1. Record production entry at stg_from
        prod_res = ProductionService.record_stage_production(
            db_session,
            RecordStageProductionRequest(
                wo_number=wo_num,
                stage=stg_from,
                good_qty=50,
                rejected_quantity=0,
                machine_id="M-LATHE-01",
                operator_name="Tester",
                shift="Shift A"
            ),
            current_user=user
        )
        assert prod_res.stage_onhand_available == 50, f"Stage {stg_from} must have 50 on-hand available for movement"

        # 2. Check tracking returns correct movable_from_stage
        tracking = WorkOrderService.get_tracking_detail(db_session, wo_num)
        step = next((s for s in tracking.timeline if s.stage == stg_from), None)
        assert step is not None
        assert step.on_hand_wip == 50, f"Timeline step for {stg_from} must show 50 on_hand_wip"

        # 3. Move parts to stg_to
        mov_res = ProductionService.move_parts(
            db_session,
            MovePartsRequest(
                wo_number=wo_num,
                from_stage=stg_from,
                to_stage=stg_to,
                quantity_moved=50,
                rejected_quantity=0,
                machine_id="M-LATHE-01",
                operator_name="Tester",
                shift="Shift A"
            ),
            current_user=user
        )
        assert mov_res.quantity_moved == 50
        assert mov_res.from_stage == stg_from
        assert mov_res.to_stage == stg_to

    # At the end, all 50 pieces have arrived in DISPATCH
    dispatch_wip = db_session.query(StageWIP).filter(
        StageWIP.work_order.has(wo_number=wo_num),
        StageWIP.stage == "DISPATCH"
    ).first()
    assert dispatch_wip is not None
    assert dispatch_wip.ent_qty == 50
