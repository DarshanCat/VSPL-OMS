import io
import csv
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from sqlalchemy.pool import StaticPool
import app.models  # Register all models on Base.metadata
from app.core.database import Base, get_db
from app.main import app
from app.services.seed_service import seed_database_if_empty
from app.services.oms_integration_service import OMSIntegrationService, link_wo_to_oar
from app.schemas.oms import WOOarLinkRow
from app.models.work_order import WorkOrder
from app.models.order import Order
from app.models.oms_exception import OMSException
from app.models.user import User, UserRole

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    seed_database_if_empty(session)
    yield session
    session.close()
    engine.dispose()

def test_link_wo_to_oar_idempotent_and_already_linked(db_session):
    row = WOOarLinkRow(
        wo_id="WO-TEST-001",
        oar_no="OAR-TEST-001",
        customer="Adani New Industries Limited",
        customer_po_number="PO-ADANI-101",
        part_no="W1402-N0432-100",
        grade="Standard",
        po_quantity=100,
        wo_quantity=10,
        cust_delivery_date="2026-10-30"
    )

    # First run: should create OAR and WO
    res1 = link_wo_to_oar(db_session, [row])
    assert res1.linked_count == 1
    assert res1.already_linked_count == 0
    assert "WO-TEST-001" in res1.linked
    assert len(res1.created_oars) == 1

    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-TEST-001").first()
    assert wo is not None
    assert wo.physical_wo_qty == 10
    assert wo.order is not None
    assert wo.order.customer_po == "PO-ADANI-101"

    # Second run (exact same input): must be idempotent and report already_linked
    res2 = link_wo_to_oar(db_session, [row])
    assert res2.linked_count == 0
    assert res2.already_linked_count == 1
    assert "WO-TEST-001" in res2.already_linked
    assert len(res2.created_oars) == 0

    # Ensure no duplicate WOs were created
    count = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-TEST-001").count()
    assert count == 1

def test_link_wo_to_oar_missing_fields_and_non_positive_qty(db_session):
    # Missing customer_po_number
    row_no_po = WOOarLinkRow(
        wo_id="WO-BAD-01",
        customer="Siemens",
        customer_po_number="",
        part_no="PART-1",
        wo_quantity=10
    )
    # Missing part_no
    row_no_part = WOOarLinkRow(
        wo_id="WO-BAD-02",
        customer="Siemens",
        customer_po_number="PO-102",
        part_no="",
        wo_quantity=10
    )
    # Missing customer
    row_no_cust = WOOarLinkRow(
        wo_id="WO-BAD-03",
        customer="",
        customer_po_number="PO-103",
        part_no="PART-1",
        wo_quantity=10
    )
    # wo_quantity <= 0
    row_zero_qty = WOOarLinkRow(
        wo_id="WO-BAD-04",
        customer="Siemens",
        customer_po_number="PO-104",
        part_no="PART-1",
        wo_quantity=0
    )

    res = link_wo_to_oar(db_session, [row_no_po, row_no_part, row_no_cust, row_zero_qty])
    assert res.linked_count == 0
    assert res.exceptions_count == 4
    for exc in res.exceptions:
        assert exc.type == "missing_field"

    # Verify exceptions recorded in DB
    db_excs = db_session.query(OMSException).filter(OMSException.exception_type == "missing_field").all()
    assert len(db_excs) == 4

def test_one_accepted_order_one_oar_rule(db_session):
    """Multiple WOs with the same (customer_po_number, part_no) must link to the SAME OAR."""
    row1 = WOOarLinkRow(
        wo_id="WO-BATCH-01",
        oar_no="OAR-SHARED-01",
        customer="Adani New Industries Limited",
        customer_po_number="PO-SHARED-999",
        part_no="PART-SHARED-999",
        po_quantity=500,
        wo_quantity=50
    )
    row2 = WOOarLinkRow(
        wo_id="WO-BATCH-02",
        oar_no="OAR-SHARED-01",
        customer="Adani New Industries Limited",
        customer_po_number="PO-SHARED-999",
        part_no="PART-SHARED-999",
        po_quantity=500,
        wo_quantity=60
    )

    res = link_wo_to_oar(db_session, [row1, row2])
    assert res.linked_count == 2
    assert res.created_oars_count == 1  # Only 1 OAR created

    wo1 = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-BATCH-01").first()
    wo2 = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-BATCH-02").first()
    assert wo1.order_id == wo2.order_id
    assert wo1.order.po_qty == 500  # PO quantity remains unchanged

def test_oar_mismatch_proceeds_with_db_truth(db_session):
    """If row.oar_no != existing_oar.oar_no, record oar_mismatch exception and proceed using DB OAR."""
    # First, create WO-01 under OAR-ORIGINAL
    row1 = WOOarLinkRow(
        wo_id="WO-MIS-01",
        oar_no="OAR-ORIGINAL",
        customer="Milacron India Pvt Ltd",
        customer_po_number="PO-MIL-555",
        part_no="PART-MIL-555",
        po_quantity=100,
        wo_quantity=20
    )
    link_wo_to_oar(db_session, [row1])

    # Second, send WO-02 with the same PO/Part, but sheet carries 'OAR-DIFFERENT'
    row2 = WOOarLinkRow(
        wo_id="WO-MIS-02",
        oar_no="OAR-DIFFERENT",
        customer="Milacron India Pvt Ltd",
        customer_po_number="PO-MIL-555",
        part_no="PART-MIL-555",
        po_quantity=100,
        wo_quantity=25
    )
    res2 = link_wo_to_oar(db_session, [row2])
    assert res2.linked_count == 1
    assert any(e.type == "oar_mismatch" for e in res2.exceptions)

    wo2 = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-MIS-02").first()
    assert wo2 is not None
    assert wo2.order.oar_number == "OAR-ORIGINAL"  # Used DB's source of truth

def test_customer_mismatch_aborts_wo(db_session):
    """If existing_oar has customer A, but row specifies customer B, record customer_mismatch and do NOT link."""
    row1 = WOOarLinkRow(
        wo_id="WO-CUST-01",
        oar_no="OAR-CUST-01",
        customer="Customer Alpha",
        customer_po_number="PO-CONFLICT-1",
        part_no="PART-CONFLICT-1",
        wo_quantity=10
    )
    link_wo_to_oar(db_session, [row1])

    row2 = WOOarLinkRow(
        wo_id="WO-CUST-02",
        oar_no="OAR-CUST-01",
        customer="Customer Beta",  # Completely different customer
        customer_po_number="PO-CONFLICT-1",
        part_no="PART-CONFLICT-1",
        wo_quantity=10
    )
    res2 = link_wo_to_oar(db_session, [row2])
    assert res2.linked_count == 0
    assert any(e.type == "customer_mismatch" for e in res2.exceptions)

    # WO-CUST-02 must NOT have been created
    wo2 = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-CUST-02").first()
    assert wo2 is None

def test_api_endpoint_wo_oar_link_json_and_csv(db_session):
    """Integration test against POST /api/v1/oms/wo-oar-link endpoint with auth."""
    from app.core.security import create_access_token
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        token = create_access_token(data={"sub": "planner@vspl.com", "role": "planner"})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. JSON Batch test
        json_payload = [
            {
                "wo_id": "WO-API-101",
                "oar_no": "OAR-API-101",
                "customer": "Test Customer Ltd",
                "customer_po_number": "PO-API-001",
                "part_no": "PART-API-001",
                "wo_quantity": 15,
                "po_quantity": 50,
                "cust_delivery_date": "2026-10-25"
            }
        ]
        resp = client.post("/api/v1/oms/wo-oar-link", json=json_payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["linked_count"] == 1
        assert "WO-API-101" in data["linked"]

        # 2. Re-send exact same JSON (Idempotency test via API)
        resp_idem = client.post("/api/v1/oms/wo-oar-link", json=json_payload, headers=headers)
        assert resp_idem.status_code == 200
        data_idem = resp_idem.json()
        assert data_idem["already_linked_count"] == 1
        assert data_idem["linked_count"] == 0

        # 3. CSV Upload test
        csv_content = """WO,OAR,Customer,Part No,Customer PO Number,PO Qty,WO Qty,Setup Date,Already_in_Software
WO-API-102,OAR-API-102,Test Customer Ltd,PART-API-002,PO-API-002,100,20,2026-10-28,False
WO-API-103,OAR-API-102,Test Customer Ltd,PART-API-002,PO-API-002,100,0,2026-10-28,False
"""
        files = {"file": ("test_import.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        resp_csv = client.post("/api/v1/oms/wo-oar-link", files=files, headers=headers)
        assert resp_csv.status_code == 200
        data_csv = resp_csv.json()
        assert data_csv["linked_count"] == 1
        assert "WO-API-102" in data_csv["linked"]
        assert data_csv["exceptions_count"] == 1
        assert data_csv["exceptions"][0]["type"] == "missing_field"
    finally:
        app.dependency_overrides.pop(get_db, None)

