import pytest
from datetime import date, datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.security import get_password_hash, create_access_token
from app.models.order import Customer, Order, OrderStatus, Part
from app.models.master_data import POMaster, POLine, POStatus
from app.models.work_order import WorkOrder, WOStatus
from app.models.packing import PackingRecord
from app.models.user import User, UserRole
from app.services.work_order_service import WorkOrderService
from app.services.dispatch_service import DispatchService
from app.schemas.dispatch import DispatchRequest


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()


@pytest.fixture
def client(db_session):
    return TestClient(app)


def _planner(db):
    user = User(
        email="planner_merge@vspl.com",
        hashed_password=get_password_hash("pass123"),
        full_name="Merge Planner",
        role=UserRole.PLANNER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, create_access_token(data={"sub": user.email, "role": user.role.value})


def test_merge_oars_validation_allocation_and_dispatch_closes_oars_and_pos(client, db_session):
    user, token = _planner(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    cust1 = Customer(customer_code="BLV", name="Bilva Tech")
    cust2 = Customer(customer_code="TMI", name="TMI Corp")
    part1 = Part(part_number="BLV3", description="BLV3 Sleeve")
    part2 = Part(part_number="TMI222", description="TMI Sleeve")
    db_session.add_all([cust1, cust2, part1, part2])
    db_session.commit()

    po1 = POMaster(po_number="PO-M-001", customer_id=cust1.id, po_date=date(2026, 11, 1), status=POStatus.OPEN)
    po2 = POMaster(po_number="PO-M-002", customer_id=cust1.id, po_date=date(2026, 11, 2), status=POStatus.OPEN)
    db_session.add_all([po1, po2])
    db_session.commit()

    line1 = POLine(po_id=po1.id, part_id=part1.id, po_qty=100, unit_price=500.0)
    line2 = POLine(po_id=po2.id, part_id=part1.id, po_qty=50, unit_price=500.0)
    db_session.add_all([line1, line2])
    db_session.commit()

    oar1 = Order(
        oar_number="OAR-M-001",
        customer_id=cust1.id,
        part_id=part1.id,
        customer_po="PO-M-001",
        po_qty=100,
        delivery_date=date(2026, 11, 20),
        status=OrderStatus.ACCEPT,
        po_line_id=line1.id,
    )
    oar2 = Order(
        oar_number="OAR-M-002",
        customer_id=cust1.id,
        part_id=part1.id,
        customer_po="PO-M-002",
        po_qty=50,
        delivery_date=date(2026, 11, 25),
        status=OrderStatus.ACCEPT,
        po_line_id=line2.id,
    )
    oar_diff_part = Order(
        oar_number="OAR-M-PART",
        customer_id=cust1.id,
        part_id=part2.id,
        customer_po="PO-M-003",
        po_qty=20,
        status=OrderStatus.ACCEPT,
    )
    oar_diff_cust = Order(
        oar_number="OAR-M-CUST",
        customer_id=cust2.id,
        part_id=part1.id,
        customer_po="PO-M-004",
        po_qty=20,
        status=OrderStatus.ACCEPT,
    )
    db_session.add_all([oar1, oar2, oar_diff_part, oar_diff_cust])
    db_session.commit()

    # Reject mismatched part
    bad_part = client.post(
        "/api/v1/operations/work-orders/merge",
        json={"oar_allocations": [{"oar_number": "OAR-M-001", "qty": 100}, {"oar_number": "OAR-M-PART", "qty": 20}]},
        headers=headers,
    )
    assert bad_part.status_code == 400
    assert "same part" in bad_part.json()["detail"].lower()

    # Reject mismatched customer
    bad_cust = client.post(
        "/api/v1/operations/work-orders/merge",
        json={"oar_allocations": [{"oar_number": "OAR-M-001", "qty": 100}, {"oar_number": "OAR-M-CUST", "qty": 20}]},
        headers=headers,
    )
    assert bad_cust.status_code == 400
    assert "same customer" in bad_cust.json()["detail"].lower()

    # Merge OAR-M-001 (100) + OAR-M-002 (50) into WO-M-100 (150)
    res = client.post(
        "/api/v1/operations/work-orders/merge",
        json={
            "oar_allocations": [
                {"oar_number": "OAR-M-001", "qty": 100},
                {"oar_number": "OAR-M-002", "qty": 50},
            ],
            "wo_number": "WO-M-100",
            "casting_process": "CENTRIFUGAL",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["wo_number"] == "WO-M-100"
    assert body["physical_wo_qty"] == 150
    assert "OAR-M-001" in body["oar_number"] and "OAR-M-002" in body["oar_number"]

    # Both OARs report exact allocated & remaining qty
    s1 = WorkOrderService.build_oar_summary(db_session, oar1)
    s2 = WorkOrderService.build_oar_summary(db_session, oar2)
    assert s1.allocated_qty == 100 and s1.remaining_qty == 0
    assert s2.allocated_qty == 50 and s2.remaining_qty == 0
    assert s2.work_orders[0].wo_number == "WO-M-100"

    # Search by secondary OAR or PO finds the merged WO
    wo_search = WorkOrderService.list_work_orders(db_session, search="OAR-M-002")
    assert len(wo_search) == 1
    assert wo_search[0].wo_number == "WO-M-100"
    assert wo_search[0].is_merged is True
    assert len(wo_search[0].merged_oars) == 2

    # Simulate Packing ready for dispatch and full Dispatch (150 pcs)
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-M-100").first()
    wo.released_by = "Planner"
    wo.release_date = datetime.now(timezone.utc)
    wo.status = WOStatus.IN_PRODUCTION
    pr = PackingRecord(
        work_order_id=wo.id,
        received_qty=150,
        packed_qty=150,
        ready_for_dispatch_qty=150,
        dispatched_qty=0,
        pending_qty=0,
        status="Ready-for-Dispatch",
    )
    db_session.add(pr)
    db_session.commit()

    # Replace route to exclude BSR requirement for direct dispatch test
    for r in wo.routes:
        if r.stage == "BSR":
            db_session.delete(r)
    db_session.commit()

    disp_res = DispatchService.execute_dispatch(
        db_session,
        DispatchRequest(
            wo_number="WO-M-100",
            dispatched_quantity=150,
            invoice_number="INV-M-100",
            payment_status="PAID",
        ),
        current_user=user,
    )
    assert disp_res.dispatched_quantity == 150

    db_session.expire_all()
    # Both OARs are 100% fulfilled (shortfall 0) AND both POs are closed
    s1_after = WorkOrderService.build_oar_summary(db_session, oar1)
    s2_after = WorkOrderService.build_oar_summary(db_session, oar2)
    assert s1_after.oar_fulfilled == 100 and s1_after.oar_shortfall == 0
    assert s2_after.oar_fulfilled == 50 and s2_after.oar_shortfall == 0
    assert db_session.query(POMaster).filter(POMaster.id == po1.id).first().status == POStatus.CLOSED
    assert db_session.query(POMaster).filter(POMaster.id == po2.id).first().status == POStatus.CLOSED


def test_delete_unreleased_merged_wo_frees_both_oars(client, db_session):
    _, token = _planner(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    cust = Customer(customer_code="BLV2", name="Bilva 2")
    part = Part(part_number="BLV9", description="BLV9")
    db_session.add_all([cust, part])
    db_session.commit()

    o1 = Order(oar_number="OAR-D1", customer_id=cust.id, part_id=part.id, customer_po="P1", po_qty=60, status=OrderStatus.ACCEPT)
    o2 = Order(oar_number="OAR-D2", customer_id=cust.id, part_id=part.id, customer_po="P2", po_qty=40, status=OrderStatus.ACCEPT)
    db_session.add_all([o1, o2])
    db_session.commit()

    res = client.post(
        "/api/v1/operations/work-orders/merge",
        json={
            "oar_allocations": [{"oar_number": "OAR-D1", "qty": 60}, {"oar_number": "OAR-D2", "qty": 40}],
            "wo_number": "WO-M-DEL",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text

    del_res = client.delete("/api/v1/work-orders/WO-M-DEL", headers=headers)
    assert del_res.status_code == 200, del_res.text
    db_session.expire_all()

    assert WorkOrderService.build_oar_summary(db_session, o1).remaining_qty == 60
    assert WorkOrderService.build_oar_summary(db_session, o2).remaining_qty == 40
