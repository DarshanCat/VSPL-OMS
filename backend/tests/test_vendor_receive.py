import uuid
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.user import User, UserRole
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WORoute
from app.models.vendor import VendorDispatch
from app.models.production_movement import StageWIP, ProductionMovement
from app.services.vendor_service import VendorService


def _setup_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_receive_from_vendor_creates_movement_with_movement_id_and_part():
    db = _setup_db()

    user = User(full_name="Quality Receiver", email="receiver@test.com", hashed_password="pw", role=UserRole.ADMIN)
    cust = Customer(name="Customer Test", customer_code="CT")
    part = Part(part_number="PART-VEND-1")
    db.add_all([user, cust, part])
    db.flush()

    order = Order(customer_id=cust.id, part_id=part.id, customer_po="PO-VEND-1", po_qty=200, status=OrderStatus.ACCEPT)
    db.add(order)
    db.flush()

    wo = WorkOrder(wo_number="WO-VEND-001", order_id=order.id, physical_wo_qty=200, current_stage="F2")
    db.add(wo)
    db.flush()

    r1 = WORoute(work_order_id=wo.id, stage="F1", sequence=1, stage_target_qty=200)
    r2 = WORoute(work_order_id=wo.id, stage="F2", sequence=2, stage_target_qty=200)
    r3 = WORoute(work_order_id=wo.id, stage="FI", sequence=3, stage_target_qty=200)
    db.add_all([r1, r2, r3])

    wip_f2 = StageWIP(work_order_id=wo.id, stage="F2", ent_qty=200, ok_qty=200, inproc_qty=0, available_wip=200)
    db.add(wip_f2)

    disp = VendorDispatch(
        work_order_id=wo.id,
        dispatch_stage="F2",
        vendor_name="Subcontractor X",
        dc_number="DC-2026-001",
        dispatched_qty=100,
        target_return_stage="FI",
        status="AT_VENDOR",
    )
    db.add(disp)
    db.commit()

    # Receive 60 pcs into FI
    res1 = VendorService.receive_from_vendor(
        db=db,
        dispatch_id=str(disp.id),
        received_qty=60,
        scrap_qty=0,
        destination_stage="FI",
        inward_dc="IDC-101",
        remarks="First batch ok",
        current_user=user,
    )

    assert res1["success"] is True
    assert res1["received_qty"] == 60
    assert res1["status"] == "PARTIALLY_RECEIVED"
    assert res1["current_stage"] == "FI"

    # Verify ProductionMovement row was created with valid movement_id and part_id
    mov1 = db.query(ProductionMovement).filter(ProductionMovement.work_order_id == wo.id).first()
    assert mov1 is not None
    assert mov1.movement_id == "MOV-000001"
    assert mov1.part_id == part.id
    assert mov1.quantity_moved == 60
    assert mov1.to_stage == "FI"
    assert mov1.production_type == "VENDOR"

    # Receive remaining 40 pcs back to F2
    res2 = VendorService.receive_from_vendor(
        db=db,
        dispatch_id=str(disp.id),
        received_qty=40,
        scrap_qty=0,
        destination_stage="F2",
        inward_dc="IDC-102",
        remarks="Remaining returned to F2",
        current_user=user,
    )

    assert res2["success"] is True
    assert res2["status"] == "RECEIVED"
    assert res2["current_stage"] == "F2"

    movs = db.query(ProductionMovement).filter(ProductionMovement.work_order_id == wo.id).order_by(ProductionMovement.created_at).all()
    assert len(movs) == 2
    assert movs[1].movement_id == "MOV-000002"
    assert movs[1].to_stage == "F2"
