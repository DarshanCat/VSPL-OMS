import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.order import Customer, Order, OrderStatus, Part
from app.models.work_order import WorkOrder
from app.models.production import ProductionUpdate, ProductionStatus
from app.models.vendor import VendorDispatch
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.core.security import get_password_hash, create_access_token


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


def _get_token(db, email: str, role: UserRole) -> str:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            hashed_password=get_password_hash("pass123"),
            full_name=f"Test {role.value}",
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return create_access_token(data={"sub": user.email, "role": user.role.value})


def _ensure_order(db, oar_number: str = "OAR-8536", po_qty: int = 150) -> Order:
    cust = db.query(Customer).filter(Customer.customer_code == "BLV").first()
    if not cust:
        cust = Customer(customer_code="BLV", name="BLV Test Customer")
        db.add(cust)
        db.commit()
        db.refresh(cust)

    part = db.query(Part).filter(Part.part_number == "BLV3").first()
    if not part:
        part = Part(part_number="BLV3", description="BLV3 (DIA 135 X 40)")
        db.add(part)
        db.commit()
        db.refresh(part)

    order = Order(
        oar_number=oar_number,
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO2627-BTPL412",
        po_qty=po_qty,
        status=OrderStatus.ACCEPT,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def test_delete_unreleased_wo_frees_oar_qty(client, db_session):
    order = _ensure_order(db_session, "OAR-8536", 150)
    token = _get_token(db_session, "planner_wo_del@vspl.com", UserRole.PLANNER)
    headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post(
        "/api/v1/operations/work-orders",
        json={
            "oar_number": "OAR-8536",
            "wo_number": "WO-17920",
            "physical_wo_qty": 150,
            "casting_process": "CENTRIFUGAL",
        },
        headers=headers,
    )
    assert create_res.status_code == 200, create_res.text

    del_res = client.delete("/api/v1/work-orders/WO-17920", headers=headers)
    assert del_res.status_code == 200, del_res.text
    payload = del_res.json()
    assert payload["success"] is True
    assert payload["wo_number"] == "WO-17920"
    assert payload["oar_number"] == "OAR-8536"
    assert payload["freed_qty"] == 150

    db_session.expire_all()
    assert db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-17920").first() is None
    assert db_session.query(Order).filter(Order.id == order.id).first() is not None

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "WO_DELETED", AuditLog.details.like("%WO-17920%"))
        .first()
    )
    assert audit is not None

    # Confirm 404 when deleting again or querying tracking
    second_del = client.delete("/api/v1/work-orders/WO-17920", headers=headers)
    assert second_del.status_code == 404

    # Confirm same OAR quantity can be re-allocated immediately
    recreate_res = client.post(
        "/api/v1/operations/work-orders",
        json={
            "oar_number": "OAR-8536",
            "wo_number": "WO-17921",
            "physical_wo_qty": 150,
            "casting_process": "CENTRIFUGAL",
        },
        headers=headers,
    )
    assert recreate_res.status_code == 200, recreate_res.text


def test_delete_wo_blocks_released_activity_and_unauthorized(client, db_session):
    _ensure_order(db_session, "OAR-DEL-002", 150)
    planner_token = _get_token(db_session, "planner_wo_del@vspl.com", UserRole.PLANNER)
    op_token = _get_token(db_session, "op_wo_del@vspl.com", UserRole.OPERATOR)

    for wo_num in ("WO-DEL-REL", "WO-DEL-PROD", "WO-DEL-VEND"):
        res = client.post(
            "/api/v1/operations/work-orders",
            json={
                "oar_number": "OAR-DEL-002",
                "wo_number": wo_num,
                "physical_wo_qty": 40,
            },
            headers={"Authorization": f"Bearer {planner_token}"},
        )
        assert res.status_code == 200, res.text

    # Unauthorized operator role blocked (403)
    op_res = client.delete(
        "/api/v1/work-orders/WO-DEL-REL",
        headers={"Authorization": f"Bearer {op_token}"},
    )
    assert op_res.status_code == 403

    # Mark released -> blocked (400)
    wo_rel = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-DEL-REL").first()
    wo_rel.released_by = "Planner"
    wo_rel.release_date = datetime.now(timezone.utc)
    db_session.commit()

    rel_res = client.delete(
        "/api/v1/work-orders/WO-DEL-REL",
        headers={"Authorization": f"Bearer {planner_token}"},
    )
    assert rel_res.status_code == 400
    assert "released" in rel_res.json()["detail"].lower()

    # Non-admin cannot use force_unstarted_release=true (403)
    non_admin_force = client.delete(
        "/api/v1/work-orders/WO-DEL-REL?force_unstarted_release=true",
        headers={"Authorization": f"Bearer {planner_token}"},
    )
    assert non_admin_force.status_code == 403

    # Admin can delete unstarted released WO with force_unstarted_release=true
    admin_token = _get_token(db_session, "admin_wo_del@vspl.com", UserRole.ADMIN)
    admin_force = client.delete(
        "/api/v1/work-orders/WO-DEL-REL?force_unstarted_release=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_force.status_code == 200, admin_force.text
    assert db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-DEL-REL").first() is None

    # Add ProductionUpdate -> blocked (400)
    wo_prod = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-DEL-PROD").first()
    pu = ProductionUpdate(
        work_order_id=wo_prod.id,
        stage="F1",
        good_qty=5,
        reject_qty=0,
        status=ProductionStatus.COMPLETED,
    )
    db_session.add(pu)
    db_session.commit()

    prod_res = client.delete(
        "/api/v1/work-orders/WO-DEL-PROD",
        headers={"Authorization": f"Bearer {planner_token}"},
    )
    assert prod_res.status_code == 400
    assert "production updates" in prod_res.json()["detail"].lower()

    # Add VendorDispatch -> blocked (400)
    wo_vend = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-DEL-VEND").first()
    vd = VendorDispatch(
        work_order_id=wo_vend.id,
        vendor_name="Sharada Engineering",
        dc_number="DC-001",
        dispatched_qty=10,
        dispatch_stage="F2",
        status="AT_VENDOR",
    )
    db_session.add(vd)
    db_session.commit()

    vend_res = client.delete(
        "/api/v1/work-orders/WO-DEL-VEND",
        headers={"Authorization": f"Bearer {planner_token}"},
    )
    assert vend_res.status_code == 400
    assert "vendor dispatches" in vend_res.json()["detail"].lower()
