import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.master_data import POMaster, POLine, POStatus
from app.models.production_movement import StageWIP
from app.schemas.operations import OrderIntakeCreate, WorkOrderCreatePayload
from app.services.operations_service import OperationsService
from app.services.work_order_service import WorkOrderService

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()

def test_sales_creates_oar_only_no_wos(db_session):
    cust = Customer(customer_code="FLOW", name="Flow Controls", is_active=True)
    part = Part(part_number="FLOW-V01", description="Control Valve Body")
    db_session.add_all([cust, part])
    db_session.flush()

    po = POMaster(po_number="PO-FLOW-101", customer_id=cust.id, status=POStatus.OPEN)
    db_session.add(po)
    db_session.flush()

    po_line = POLine(po_id=po.id, part_id=part.id, customer_part_number="FLOW-VALVE-CPN", po_qty=100)
    db_session.add(po_line)
    db_session.commit()

    # Step 1: Sales creates OAR against PO line (create_wos=False)
    intake_payload = OrderIntakeCreate(
        customer_code="FLOW",
        customer_name="Flow Controls",
        customer_po="PO-FLOW-101",
        part_number="FLOW-V01",
        po_quantity=100,
        max_batch_size=50,
        delivery_date=date(2026, 11, 1),
        source_type="po",
        po_line_id=str(po_line.id),
        create_wos=False,
    )

    res = OperationsService.create_order_intake(db_session, intake_payload)
    assert res.success is True
    assert res.oar_number.startswith("OAR-")
    assert len(res.wos_created) == 0  # Crucial: NO WOs generated yet!

    # Verify Order created and PO line allocated
    order = db_session.query(Order).filter(Order.id == res.order_id).first()
    assert order is not None
    assert order.po_qty == 100
    assert len(order.work_orders) == 0

def test_planner_generates_wo_from_oar(db_session):
    cust = Customer(customer_code="BHEL", name="Bharat Heavy Electricals", is_active=True)
    part = Part(part_number="BHEL-P01", description="Turbine Rotor Shaft")
    db_session.add_all([cust, part])
    db_session.flush()

    order = Order(
        oar_number="OAR-9901",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-BHEL-777",
        po_qty=100,
        max_batch_size=50,
        delivery_date=date(2026, 12, 1),
        status=OrderStatus.ACCEPT,
    )
    db_session.add(order)
    db_session.commit()

    # Step 2: Planner generates Work Order for this OAR with custom date & quantity
    wo_payload = WorkOrderCreatePayload(
        oar_number="OAR-9901",
        wo_number="WO-9901-A",
        physical_wo_qty=40,
        wo_date=date(2026, 10, 15),
        casting_process="CENTRIFUGAL",
    )

    wo_res = OperationsService.create_work_order(db_session, wo_payload)
    assert wo_res.success is True
    assert wo_res.wo_number == "WO-9901-A"
    assert wo_res.oar_number == "OAR-9901"
    assert wo_res.physical_wo_qty == 40
    assert wo_res.release_status == "AWAITING_ENG_RELEASE"

    # Verify second WO allocation works up to remaining (60)
    wo_payload2 = WorkOrderCreatePayload(
        oar_number="OAR-9901",
        physical_wo_qty=60,
        wo_date=date(2026, 10, 16),
    )
    wo_res2 = OperationsService.create_work_order(db_session, wo_payload2)
    assert wo_res2.success is True
    assert wo_res2.physical_wo_qty == 60

    # Over-allocation should fail with 400
    with pytest.raises(Exception):
        OperationsService.create_work_order(
            db_session,
            WorkOrderCreatePayload(oar_number="OAR-9901", physical_wo_qty=10)
        )

def test_movable_work_orders_queue(db_session):
    cust = Customer(customer_code="CUST1", name="Customer One", is_active=True)
    part = Part(part_number="PART1", description="Part One")
    db_session.add_all([cust, part])
    db_session.flush()

    order = Order(
        oar_number="OAR-111",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-111",
        po_qty=50,
        max_batch_size=50,
        delivery_date=date(2026, 10, 25),
    )
    db_session.add(order)
    db_session.flush()

    wo = WorkOrder(
        wo_number="WO-5001",
        order_id=order.id,
        physical_wo_qty=50,
        current_stage="F1",
        status=WOStatus.IN_PRODUCTION,
    )
    db_session.add(wo)
    db_session.flush()

    r1 = WORoute(work_order_id=wo.id, stage="F1", sequence=1, stage_target_qty=50)
    r2 = WORoute(work_order_id=wo.id, stage="F2", sequence=2, stage_target_qty=50)
    r3 = WORoute(work_order_id=wo.id, stage="DISPATCH", sequence=3, stage_target_qty=50)
    db_session.add_all([r1, r2, r3])

    # 10 pieces produced at F1, waiting to move to F2
    wip_f1 = StageWIP(work_order_id=wo.id, stage="F1", available_wip=10)
    wip_f2 = StageWIP(work_order_id=wo.id, stage="F2", available_wip=0)
    db_session.add_all([wip_f1, wip_f2])
    db_session.commit()

    movable = WorkOrderService.list_movable_work_orders(db_session)
    assert len(movable) == 1
    assert movable[0].wo_number == "WO-5001"
    assert movable[0].oar_number == "OAR-111"
    assert movable[0].from_stage == "F1"
    assert movable[0].to_stage == "F2"
    assert movable[0].movable_wip == 10

def test_planner_divides_quantity_into_multiple_wos_and_allows_overrun(db_session):
    cust = Customer(customer_code="ACCU", name="Accutech CNC", is_active=True)
    part = Part(part_number="SMX4", description="Bronze Bushing SMX4")
    db_session.add_all([cust, part])
    db_session.flush()

    order = Order(
        oar_number="OAR-0229",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-12500",
        po_qty=20,
        max_batch_size=20,
        status=OrderStatus.ACCEPT,
    )
    db_session.add(order)
    db_session.commit()

    # Planner divides quantity into 2 Work Orders: 10 pcs and 10 pcs
    payload = WorkOrderCreatePayload(
        oar_number="OAR-0229",
        wo_number="WO-17618",
        physical_wo_qty=20,
        wo_quantities=[10, 10],
        wo_date=date(2026, 10, 15),
    )
    res = OperationsService.create_work_order(db_session, payload)
    assert res.success is True
    assert len(res.wos_created) == 2
    assert res.wos_created[0] == "WO-17618"
    assert res.wo_quantities == [10, 10]
    assert res.physical_wo_qty == 20

    # Test allow_overrun when remaining is 0
    overrun_payload = WorkOrderCreatePayload(
        oar_number="OAR-0229",
        physical_wo_qty=25,
        allow_overrun=True,
    )
    res_overrun = OperationsService.create_work_order(db_session, overrun_payload)
    assert res_overrun.success is True
    assert res_overrun.physical_wo_qty == 25

