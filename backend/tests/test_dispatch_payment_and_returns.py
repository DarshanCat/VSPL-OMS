import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, auto_migrate_schema
from app.main import app
from app.models.dispatch import Dispatch
from app.models.customer_return import CustomerReturn
from app.models.work_order import WorkOrder
from app.models.production_movement import StageWIP
from app.models.master_data import POMaster, POLine, POStatus
from app.models.order import Customer, Part, Order
from app.schemas.operations import OrderIntakeCreate
from app.services.operations_service import OperationsService


import uuid
from app.api.deps import get_current_user
from app.models.user import User, UserRole


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    auto_migrate_schema()
    yield


@pytest.fixture
def client():
    mock_user = User(
        id=uuid.uuid4(),
        email="dispatch.officer@vijayspheroidals.com",
        full_name="Dispatch Officer",
        role=UserRole.DISPATCH,
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_dispatch_invoice_payment_workflow(client):
    db = SessionLocal()
    try:
        # Create an order and work order via intake service
        intake = OrderIntakeCreate(
            customer_code="CUST-PAY-01",
            customer_name="Payment Test Motors",
            customer_po="PO-PAY-99",
            part_number="PART-PAY-01",
            po_quantity=100,
            order_type="Production",
            create_wos=True,
            max_batch_size=100
        )
        res_intake = OperationsService.create_order_intake(db, intake)
        wo_num = res_intake.wos_created[0]
        wo_obj = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

        # Create a sample dispatch
        disp = Dispatch(
            work_order_id=wo_obj.id,
            customer_po="PO-PAY-99",
            invoice_number="INV-PAY-001",
            dispatched_qty=100,
            unit_price=150.0,
            total_invoice_value=15000.0,
            payment_status="UNPAID",
            paid_amount=0.0,
        )
        db.add(disp)
        db.commit()
        db.refresh(disp)
        disp_id = str(disp.id)

        # 1. Update to PARTIALLY_PAID
        patch_res = client.patch(
            f"/api/v1/dispatch/{disp_id}/payment",
            json={
                "payment_status": "PARTIALLY_PAID",
                "paid_amount": 7500.0,
                "payment_reference": "UTR-PARTIAL-1234",
                "payment_remarks": "Advance 50% received via NEFT",
            },
        )
        assert patch_res.status_code == 200, patch_res.text
        data = patch_res.json()
        assert data["payment_status"] == "PARTIALLY_PAID"
        assert data["paid_amount"] == 7500.0
        assert data["payment_reference"] == "UTR-PARTIAL-1234"

        # 2. Update to PAID in full
        patch_res2 = client.patch(
            f"/api/v1/dispatch/{disp_id}/payment",
            json={
                "payment_status": "PAID",
                "paid_amount": 15000.0,
                "payment_reference": "UTR-FULL-5678",
                "payment_remarks": "Balance cleared",
            },
        )
        assert patch_res2.status_code == 200
        data2 = patch_res2.json()
        assert data2["payment_status"] == "PAID"
        assert data2["paid_amount"] == 15000.0

        # 3. Test invalid payment status
        invalid_res = client.patch(
            f"/api/v1/dispatch/{disp_id}/payment",
            json={"payment_status": "UNKNOWN_STATUS"},
        )
        assert invalid_res.status_code == 400

    finally:
        db.close()


def test_pricing_lookup_from_po(client):
    db = SessionLocal()
    try:
        # Create an order so customer and part are guaranteed to exist
        intake = OrderIntakeCreate(
            customer_code="CUST-PRICING-01",
            customer_name="Beta Precision",
            customer_po="PO-PRICING-88",
            part_number="PART-PRICING-01",
            po_quantity=50,
            order_type="Production",
            create_wos=False
        )
        OperationsService.create_order_intake(db, intake)

        cust = db.query(Customer).filter(Customer.customer_code == "CUST-PRICING-01").first()
        part = db.query(Part).filter(Part.part_number == "PART-PRICING-01").first()

        # Create a PO Master and line with unit price
        po_num = f"PO-PRICING-{uuid.uuid4().hex[:6]}"
        po = POMaster(
            po_number=po_num,
            customer_id=cust.id,
            status=POStatus.OPEN,
            total_value=25000.0,
        )
        db.add(po)
        db.flush()

        line = POLine(
            po_id=po.id,
            part_id=part.id,
            po_qty=50,
            unit_price=500.0,
            line_total=25000.0,
        )
        db.add(line)
        db.commit()

        # Query pricing lookup endpoint
        res = client.get(
            "/api/v1/dispatch/pricing-lookup",
            params={"customer_code": "CUST-PRICING-01", "part_number": "PART-PRICING-01"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["unit_price"] == 500.0
        assert "PO_MASTER" in data["source"]
    finally:
        db.close()


def test_customer_return_and_conversion_wo_replacement(client):
    db = SessionLocal()
    try:
        # Create an order & work order so active OAR exists
        intake = OrderIntakeCreate(
            customer_code="CUST-RET-01",
            customer_name="Returned Parts Ltd",
            customer_po="PO-RET-442",
            part_number="PART-RET-99",
            po_quantity=100,
            order_type="Production",
            create_wos=True,
            max_batch_size=100
        )
        res_intake = OperationsService.create_order_intake(db, intake)
        orig_wo_num = res_intake.wos_created[0]

        # Execute customer return with product selling value
        payload = {
            "customer_code": "CUST-RET-01",
            "customer_name": "Returned Parts Ltd",
            "customer_po": "PO-RET-442",
            "invoice_number": "INV-2026-0099",
            "original_wo_number": orig_wo_num,
            "part_number": "PART-RET-99",
            "returned_qty": 40,
            "unit_price": 325.50,
            "complaint_reason": "Bore diameter oversized by 0.05mm",
            "entry_stage": "F1",
        }

        res = client.post("/api/v1/dispatch/returns", json=payload)
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["success"] is True
        assert data["return_number"].startswith("RET-")
        assert data["returned_qty"] == 40
        assert data["unit_price"] == 325.50
        assert data["total_return_value"] == 40 * 325.50
        assert data["entry_stage"] == "F1"

        conv_wo_number = data["conversion_wo_number"]
        assert conv_wo_number is not None

        # Verify Work Order in database replaces quantity
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == conv_wo_number).first()
        assert wo is not None
        assert wo.physical_wo_qty == 40  # WO QTY REPLACED!
        assert wo.is_replacement is True
        assert "Bore diameter oversized" in (wo.replacement_reason or "")
        assert data["return_number"] in (wo.replacement_reason or "")

        # Verify Stage WIP credited
        stage_wip = db.query(StageWIP).filter(
            StageWIP.work_order_id == wo.id,
            StageWIP.stage == "F1"
        ).first()
        assert stage_wip is not None
        assert stage_wip.available_wip == 40

        # Verify listing endpoint includes this return
        list_res = client.get("/api/v1/dispatch/returns")
        assert list_res.status_code == 200
        returns_list = list_res.json()
        matching = [r for r in returns_list if r["return_number"] == data["return_number"]]
        assert len(matching) == 1
        assert matching[0]["returned_qty"] == 40
        assert matching[0]["unit_price"] == 325.50
        assert matching[0]["total_return_value"] == 13020.0
        assert matching[0]["conversion_wo_number"] == conv_wo_number

    finally:
        db.close()
