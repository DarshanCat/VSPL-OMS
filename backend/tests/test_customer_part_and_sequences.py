import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.database import Base
from app.models.order import Customer, Part, Order
from app.models.work_order import WorkOrder
from app.models.customer_part_mapping import CustomerPartMapping
from app.models.master_data import POMaster, POLine
from app.schemas.master_data import POMasterCreate, POLineCreate
from app.services.master_data_service import POMasterService
from app.services.oms_integration_service import (
    next_oar_sequence,
    next_wo_sequence,
    extract_oar_number,
    extract_wo_number,
    _normalize_oar_code,
    _normalize_wo_code,
)

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

def test_extract_oar_and_wo_numbers():
    assert extract_oar_number("OAR-8326") == 8326
    assert extract_oar_number("OAR 8326") == 8326
    assert extract_oar_number("8326") == 8326
    assert extract_oar_number("OAR8326") == 8326
    assert extract_oar_number("OAR - 8326") == 8326
    assert extract_oar_number("OAR-0001") == 1
    assert extract_oar_number("OAR-TEST-001") is None

    assert extract_wo_number("WO-16772") == 16772
    assert extract_wo_number("WO 16772") == 16772
    assert extract_wo_number("16772") == 16772
    assert extract_wo_number("WO16772") == 16772
    assert extract_wo_number("WO - 16772") == 16772
    assert extract_wo_number("WO-API-101") is None

def test_next_oar_sequence_with_dumped_numbers(db_session):
    cust = Customer(customer_code="TESTCUST", name="Test Customer", is_active=True)
    part = Part(part_number="PART-TEST-01", description="Test Part")
    db_session.add_all([cust, part])
    db_session.flush()

    # Team dumps OAR 8326
    order1 = Order(
        oar_number="OAR 8326",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-8326",
        po_qty=100,
        max_batch_size=500
    )
    db_session.add(order1)
    db_session.commit()

    # System must check existing and generate OAR-8327
    next_oar = next_oar_sequence(db_session)
    assert next_oar == "OAR-8327"

def test_next_wo_sequence_with_dumped_numbers(db_session):
    cust = Customer(customer_code="TESTCUST2", name="Test Customer 2", is_active=True)
    part = Part(part_number="PART-TEST-02", description="Test Part 2")
    db_session.add_all([cust, part])
    db_session.flush()

    order = Order(
        oar_number="OAR-1001",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-1001",
        po_qty=50,
        max_batch_size=500
    )
    db_session.add(order)
    db_session.flush()

    # Team dumps WO 16772
    wo1 = WorkOrder(
        wo_number="WO 16772",
        order_id=order.id,
        physical_wo_qty=50,
        current_stage="F1",
        projected_final_good=50,
        shortfall="No"
    )
    db_session.add(wo1)
    db_session.commit()

    # System must check existing and generate WO-16773
    next_wo = next_wo_sequence(db_session)
    assert next_wo == "WO-16773"

def test_po_creation_with_customer_part_number(db_session):
    cust = Customer(customer_code="DANFOSS", name="Danfoss Power Solutions", is_active=True)
    db_session.add(cust)
    db_session.commit()

    # Create PO with customer_part_number "RC47NN135000000092"
    req = POMasterCreate(
        po_number="PO-DANFOSS-001",
        customer_code="DANFOSS",
        lines=[
            POLineCreate(
                customer_part_number="RC47NN135000000092",
                po_qty=50,
            )
        ]
    )
    po_out = POMasterService.create_po(db_session, req)
    assert po_out.po_number == "PO-DANFOSS-001"
    assert len(po_out.lines) == 1
    line = po_out.lines[0]
    assert line.customer_part_number == "RC47NN135000000092"
    assert line.part_number is not None  # Auto-generated e.g. DANFOSS1
    assert line.po_qty == 50

    # Creating a second PO for same customer & customer_part_number should reuse internal part
    req2 = POMasterCreate(
        po_number="PO-DANFOSS-002",
        customer_code="DANFOSS",
        lines=[
            POLineCreate(
                customer_part_number="RC47NN135000000092",
                po_qty=20,
            )
        ]
    )
    po_out2 = POMasterService.create_po(db_session, req2)
    assert po_out2.lines[0].customer_part_number == "RC47NN135000000092"
    assert po_out2.lines[0].part_number == line.part_number  # Reused same internal part!

def test_po_creation_with_customer_part_in_part_number_field(db_session):
    cust = Customer(customer_code="CUMMINS", name="Cummins Technologies", is_active=True)
    db_session.add(cust)
    db_session.commit()

    # If user enters customer part number in the part_number field
    req = POMasterCreate(
        po_number="PO-CUMMINS-001",
        customer_code="CUMMINS",
        lines=[
            POLineCreate(
                part_number="RC47NN999000000001",
                po_qty=75,
            )
        ]
    )
    # Must NOT raise 404; must resolve/generate and store
    po_out = POMasterService.create_po(db_session, req)
    assert po_out.po_number == "PO-CUMMINS-001"
    assert po_out.lines[0].customer_part_number == "RC47NN999000000001"
    assert po_out.lines[0].part_number is not None
