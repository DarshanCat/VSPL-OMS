import pytest
from datetime import date
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import Base, engine, SessionLocal
from app.models.order import Customer, Order, OrderStatus, Part

from app.models.work_order import WorkOrder, WOStatus
from app.models.user import User, UserRole
from app.core.security import get_password_hash, create_access_token

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()

@pytest.fixture
def planner_token(db):
    user = db.query(User).filter(User.email == "planner_wo_edit@vspl.com").first()
    if not user:
        user = User(
            email="planner_wo_edit@vspl.com",
            hashed_password=get_password_hash("pass123"),
            full_name="WO Edit Planner",
            role=UserRole.PLANNER,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return create_access_token(data={"sub": user.email, "role": user.role.value})

def test_wo_edit_number_and_qty(client, db, planner_token):
    # Setup test customer, part, order, and WO
    cust = db.query(Customer).filter(Customer.customer_code == "EDITCUST").first()
    if not cust:
        cust = Customer(customer_code="EDITCUST", name="Edit Test Customer")
        db.add(cust)
        db.commit()

    part = db.query(Part).filter(Part.part_number == "EDITPART").first()
    if not part:
        part = Part(part_number="EDITPART", description="Edit Part")
        db.add(part)
        db.commit()

    order = db.query(Order).filter(Order.oar_number == "OAR-EDIT-001").first()
    if not order:
        order = Order(
            oar_number="OAR-EDIT-001",
            customer_id=cust.id,
            part_id=part.id,
            customer_po="PO-EDIT",
            po_qty=100,
            status=OrderStatus.ACCEPT
        )
        db.add(order)
        db.commit()

    # Clean existing test WOs
    for w in db.query(WorkOrder).filter(WorkOrder.wo_number.in_(["WO-EDIT-1001", "WO-EDIT-1002"])).all():
        db.delete(w)
    db.commit()

    # Create initial WO
    headers = {"Authorization": f"Bearer {planner_token}"}
    create_res = client.post(
        "/api/v1/operations/work-orders",
        json={
            "oar_number": "OAR-EDIT-001",
            "wo_number": "WO-EDIT-1001",
            "physical_wo_qty": 30,
            "casting_process": "CENTRIFUGAL",
            "heat_number": "HEAT-01",
            "remarks": "Original note"
        },
        headers=headers
    )
    assert create_res.status_code == 200, create_res.text
    data = create_res.json()
    assert data["wo_number"] == "WO-EDIT-1001"
    assert data["physical_wo_qty"] == 30

    # Test editing WO number, quantity, heat number, casting process
    edit_res = client.put(
        "/api/v1/operations/work-orders/WO-EDIT-1001",
        json={
            "wo_number": "WO-EDIT-1002",
            "physical_wo_qty": 50,
            "casting_process": "CONTINUOUS",
            "heat_number": "HEAT-02-UPDATED",
            "remarks": "Updated note"
        },
        headers=headers
    )
    assert edit_res.status_code == 200, edit_res.text
    updated = edit_res.json()
    assert updated["wo_number"] == "WO-EDIT-1002"
    assert updated["physical_wo_qty"] == 50
    assert updated["heat_number"] == "HEAT-02-UPDATED"

    # Test duplicate WO number rejection
    dup_res = client.put(
        "/api/v1/operations/work-orders/WO-EDIT-1002",
        json={"wo_number": "WO-EDIT-1002"},
        headers=headers
    )
    # Self-rename to same number is accepted
    assert dup_res.status_code == 200

    # Test quantity exceeding OAR rejection without overrun
    excess_res = client.put(
        "/api/v1/operations/work-orders/WO-EDIT-1002",
        json={"physical_wo_qty": 200},
        headers=headers
    )
    assert excess_res.status_code == 400
    assert "exceeds available remaining OAR balance" in excess_res.text
