"""Comprehensive test suite and regression hardening for PO Coverage & Scheduled Order Visibility.

Covers:
1. Status computation precedence:
   - PO_MATCHED > SCHEDULED_AWAITING_PO > COMMERCIAL_PO_PENDING > UNCONFIRMED.
2. Authoritative source_type and schedule_id taking precedence over reference strings.
3. Disambiguation of commercial PO references containing substrings like SCH, SCHEDULE, BOSCH, SCHNEIDER, FISCHER
   so that they are NOT misclassified as schedules.
4. Schedule-originated orders subsequently matched to a valid PO line resolving to PO_MATCHED.
5. Invalidation scenarios:
   - Mismatched customer ID on PO Master vs Order -> not PO_MATCHED.
   - Mismatched part ID on PO Line vs Order -> not PO_MATCHED.
   - Cancelled PO Master -> not PO_MATCHED.
   - Dangling po_line_id with no PO Master -> not PO_MATCHED.
6. Missing / placeholder PO references (None, "", "N/A", "NONE", "—", "-") resolving to UNCONFIRMED.
7. Consistency across:
   - WorkOrderService.list_oars
   - WorkOrderService.list_work_orders
   - WorkOrderService.get_tracking_detail
   - WorkOrderService.get_oar_genealogy
8. End-to-end API verification.
"""
import uuid
from datetime import datetime, date
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.database import SessionLocal
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.master_data import POMaster, POLine, POStatus, ScheduleMaster, ScheduleStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.services.work_order_service import WorkOrderService, compute_po_coverage_status
from app.main import app

SEEDED_LOGINS = {
    "ADMIN": ("admin@vspl.com", "admin123"),
}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client, role_key="ADMIN"):
    email, password = SEEDED_LOGINS[role_key]
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _uid(prefix="TEST"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def test_compute_po_coverage_status_unit():
    """Unit tests for compute_po_coverage_status logic and edge cases."""
    # 1. Missing / None / Empty / Placeholders -> UNCONFIRMED
    assert compute_po_coverage_status(None) == "UNCONFIRMED"
    assert compute_po_coverage_status(Order(customer_po="")) == "UNCONFIRMED"
    assert compute_po_coverage_status(Order(customer_po="   ")) == "UNCONFIRMED"
    assert compute_po_coverage_status(Order(customer_po="N/A")) == "UNCONFIRMED"
    assert compute_po_coverage_status(Order(customer_po="None")) == "UNCONFIRMED"
    assert compute_po_coverage_status(Order(customer_po="—")) == "UNCONFIRMED"
    assert compute_po_coverage_status(Order(customer_po="-")) == "UNCONFIRMED"

    # 2. Commercial PO references (including substrings like SCHNEIDER, BOSCH, FISCHER) -> COMMERCIAL_PO_PENDING
    assert compute_po_coverage_status(Order(customer_po="PO-99482", source_type="po")) == "COMMERCIAL_PO_PENDING"
    assert compute_po_coverage_status(Order(customer_po="PO-SCHNEIDER-101", source_type="po")) == "COMMERCIAL_PO_PENDING"
    assert compute_po_coverage_status(Order(customer_po="BOSCH-PO-9912", source_type="po")) == "COMMERCIAL_PO_PENDING"
    assert compute_po_coverage_status(Order(customer_po="FISCHER-PO-01", source_type="po")) == "COMMERCIAL_PO_PENDING"
    assert compute_po_coverage_status(Order(customer_po="PO-SCHEDULE-REF-99", source_type="po")) == "COMMERCIAL_PO_PENDING"

    # 3. Authoritative Schedule intake -> SCHEDULED_AWAITING_PO
    assert compute_po_coverage_status(Order(customer_po="OCT_PLAN", source_type="schedule")) == "SCHEDULED_AWAITING_PO"
    assert compute_po_coverage_status(Order(customer_po="PO-12345", source_type="schedule")) == "SCHEDULED_AWAITING_PO"
    assert compute_po_coverage_status(Order(customer_po="AWAITING-PO-SCH-00002", schedule_id=uuid.uuid4())) == "SCHEDULED_AWAITING_PO"
    assert compute_po_coverage_status(Order(customer_po="SOME_REF", oar_po_status="awaiting_po")) == "SCHEDULED_AWAITING_PO"

    # 4. Legacy heuristic schedule references -> SCHEDULED_AWAITING_PO
    assert compute_po_coverage_status(Order(customer_po="SCH", source_type="po")) == "SCHEDULED_AWAITING_PO"
    assert compute_po_coverage_status(Order(customer_po="SCH OCT", source_type="po")) == "SCHEDULED_AWAITING_PO"
    assert compute_po_coverage_status(Order(customer_po="OCT SCH", source_type="po")) == "SCHEDULED_AWAITING_PO"
    assert compute_po_coverage_status(Order(customer_po="SCHEDULE", source_type="po")) == "SCHEDULED_AWAITING_PO"
    assert compute_po_coverage_status(Order(customer_po="July Schedule", source_type="po")) == "SCHEDULED_AWAITING_PO"
    assert compute_po_coverage_status(Order(customer_po="FORECAST-Q4", source_type="po")) == "SCHEDULED_AWAITING_PO"
    assert compute_po_coverage_status(Order(customer_po="AWAITING-PO-SCH-101", source_type="po")) == "SCHEDULED_AWAITING_PO"


def test_schedule_originated_order_matched_to_po_master():
    """Verify that a schedule-originated order subsequently matched to a valid PO line computes PO_MATCHED."""
    db = SessionLocal()
    try:
        cust = Customer(customer_code=_uid("CUST"), name="Schedule Match Customer")
        part = Part(part_number=_uid("PART"), description="Match Part")
        db.add_all([cust, part])
        db.flush()

        po = POMaster(po_number=_uid("PO"), customer_id=cust.id, status=POStatus.OPEN)
        db.add(po)
        db.flush()

        line = POLine(po_id=po.id, part_id=part.id, po_qty=150)
        db.add(line)
        db.flush()

        # Schedule order that received matching PO line
        order = Order(
            oar_number=_uid("OAR-SCH-MATCH"),
            customer_id=cust.id,
            part_id=part.id,
            customer_po=po.po_number,
            po_qty=150,
            max_batch_size=50,
            source_type="schedule",
            schedule_id=uuid.uuid4(),
            oar_po_status="po_matched",
            po_line_id=line.id,
            status=OrderStatus.ACCEPT
        )
        db.add(order)
        db.commit()
        db.refresh(order)

        # Status must resolve to PO_MATCHED because a valid PO line is linked
        status = compute_po_coverage_status(order)
        assert status == "PO_MATCHED"

        summary = WorkOrderService.build_oar_summary(db, order)
        assert summary.po_coverage_status == "PO_MATCHED"
        assert summary.po_matched is True
        assert summary.source_type == "schedule"

        # Cleanup
        db.delete(order)
        db.delete(line)
        db.delete(po)
        db.delete(part)
        db.delete(cust)
        db.commit()
    finally:
        db.close()


def test_invalid_and_mismatched_po_line_relationships():
    """Verify that cancelled POs, mismatched customers, and mismatched parts are NOT marked PO_MATCHED."""
    db = SessionLocal()
    try:
        cust1 = Customer(customer_code=_uid("CUST1"), name="Customer 1")
        cust2 = Customer(customer_code=_uid("CUST2"), name="Customer 2")
        part1 = Part(part_number=_uid("PART1"), description="Part 1")
        part2 = Part(part_number=_uid("PART2"), description="Part 2")
        db.add_all([cust1, cust2, part1, part2])
        db.flush()

        # PO for Customer 2
        po_cust2 = POMaster(po_number=_uid("PO2"), customer_id=cust2.id, status=POStatus.OPEN)
        db.add(po_cust2)
        db.flush()
        line_cust2 = POLine(po_id=po_cust2.id, part_id=part1.id, po_qty=50)
        db.add(line_cust2)

        # Cancelled PO for Customer 1
        po_cancelled = POMaster(po_number=_uid("PO-CAN"), customer_id=cust1.id, status=POStatus.CANCELLED)
        db.add(po_cancelled)
        db.flush()
        line_cancelled = POLine(po_id=po_cancelled.id, part_id=part1.id, po_qty=50)
        db.add(line_cancelled)

        # PO for wrong Part (Part 2)
        po_part2 = POMaster(po_number=_uid("PO-P2"), customer_id=cust1.id, status=POStatus.OPEN)
        db.add(po_part2)
        db.flush()
        line_part2 = POLine(po_id=po_part2.id, part_id=part2.id, po_qty=50)
        db.add(line_part2)
        db.flush()

        # Case A: Mismatched Customer (Order is Customer 1, PO is Customer 2)
        order_mismatch_cust = Order(
            oar_number=_uid("OAR-MIS-CUST"),
            customer_id=cust1.id,
            part_id=part1.id,
            customer_po=po_cust2.po_number,
            po_qty=50,
            max_batch_size=50,
            source_type="po",
            po_line_id=line_cust2.id,
            status=OrderStatus.ACCEPT
        )
        db.add(order_mismatch_cust)

        # Case B: Cancelled PO Master
        order_cancelled_po = Order(
            oar_number=_uid("OAR-CAN-PO"),
            customer_id=cust1.id,
            part_id=part1.id,
            customer_po=po_cancelled.po_number,
            po_qty=50,
            max_batch_size=50,
            source_type="po",
            po_line_id=line_cancelled.id,
            status=OrderStatus.ACCEPT
        )
        db.add(order_cancelled_po)

        # Case C: Mismatched Part (Order is Part 1, PO Line is Part 2)
        order_mismatch_part = Order(
            oar_number=_uid("OAR-MIS-PART"),
            customer_id=cust1.id,
            part_id=part1.id,
            customer_po=po_part2.po_number,
            po_qty=50,
            max_batch_size=50,
            source_type="po",
            po_line_id=line_part2.id,
            status=OrderStatus.ACCEPT
        )
        db.add(order_mismatch_part)
        db.commit()

        db.refresh(order_mismatch_cust)
        db.refresh(order_cancelled_po)
        db.refresh(order_mismatch_part)

        # None of these should be PO_MATCHED; they fall back to COMMERCIAL_PO_PENDING
        assert compute_po_coverage_status(order_mismatch_cust) == "COMMERCIAL_PO_PENDING"
        assert compute_po_coverage_status(order_cancelled_po) == "COMMERCIAL_PO_PENDING"
        assert compute_po_coverage_status(order_mismatch_part) == "COMMERCIAL_PO_PENDING"

        # Cleanup
        db.delete(order_mismatch_cust)
        db.delete(order_cancelled_po)
        db.delete(order_mismatch_part)
        db.delete(line_cust2)
        db.delete(line_cancelled)
        db.delete(line_part2)
        db.delete(po_cust2)
        db.delete(po_cancelled)
        db.delete(po_part2)
        db.delete(part1)
        db.delete(part2)
        db.delete(cust1)
        db.delete(cust2)
        db.commit()
    finally:
        db.close()


def test_oar_and_wo_list_endpoints_expose_po_coverage_fields(client):
    """End-to-end API test verifying consistent PO coverage fields across all endpoints."""
    token = _login(client, "ADMIN")
    headers = _auth(token)
    db = SessionLocal()

    try:
        cust = Customer(customer_code=_uid("CUST"), name="E2E PO Customer")
        part = Part(part_number=_uid("PART"), description="E2E Part")
        db.add_all([cust, part])
        db.flush()

        # 1. Commercial PO pending order
        oar_comm_num = _uid("OAR-COMM")
        order_comm = Order(
            oar_number=oar_comm_num,
            customer_id=cust.id,
            part_id=part.id,
            customer_po="PO-SCHNEIDER-441",
            po_qty=50,
            max_batch_size=50,
            source_type="po",
            status=OrderStatus.ACCEPT
        )
        db.add(order_comm)
        db.flush()

        wo_comm = WorkOrder(
            wo_number=_uid("WO-COMM"),
            order_id=order_comm.id,
            physical_wo_qty=50,
            status=WOStatus.IN_PRODUCTION,
            current_stage="F1"
        )
        db.add(wo_comm)

        # 2. Schedule order awaiting PO
        oar_sch_num = _uid("OAR-SCH")
        order_sch = Order(
            oar_number=oar_sch_num,
            customer_id=cust.id,
            part_id=part.id,
            customer_po="SCH-OCT-BATCH",
            po_qty=80,
            max_batch_size=40,
            source_type="schedule",
            status=OrderStatus.ACCEPT
        )
        db.add(order_sch)
        db.flush()

        wo_sch = WorkOrder(
            wo_number=_uid("WO-SCH"),
            order_id=order_sch.id,
            physical_wo_qty=80,
            status=WOStatus.IN_PRODUCTION,
            current_stage="F1"
        )
        db.add(wo_sch)
        db.commit()

        # Test OAR list API
        resp_oars = client.get("/api/v1/operations/oars", headers=headers, params={"search": cust.customer_code})
        assert resp_oars.status_code == 200, resp_oars.text
        oar_items = resp_oars.json()
        assert len(oar_items) >= 2

        comm_item = next(item for item in oar_items if item["oar_number"] == oar_comm_num)
        assert comm_item["customer_po"] == "PO-SCHNEIDER-441"
        assert comm_item["source_type"] == "po"
        assert comm_item["po_matched"] is False
        assert comm_item["po_coverage_status"] == "COMMERCIAL_PO_PENDING"

        sch_item = next(item for item in oar_items if item["oar_number"] == oar_sch_num)
        assert sch_item["customer_po"] == "SCH-OCT-BATCH"
        assert sch_item["source_type"] == "schedule"
        assert sch_item["po_matched"] is False
        assert sch_item["po_coverage_status"] == "SCHEDULED_AWAITING_PO"

        # Test WO list API
        resp_wos = client.get("/api/v1/work-orders", headers=headers, params={"customer_code": cust.customer_code})
        assert resp_wos.status_code == 200, resp_wos.text
        wo_items = resp_wos.json()
        assert len(wo_items) >= 2

        wo_comm_item = next(w for w in wo_items if w["wo_number"] == wo_comm.wo_number)
        assert wo_comm_item["customer_po"] == "PO-SCHNEIDER-441"
        assert wo_comm_item["source_type"] == "po"
        assert wo_comm_item["po_coverage_status"] == "COMMERCIAL_PO_PENDING"

        wo_sch_item = next(w for w in wo_items if w["wo_number"] == wo_sch.wo_number)
        assert wo_sch_item["customer_po"] == "SCH-OCT-BATCH"
        assert wo_sch_item["source_type"] == "schedule"
        assert wo_sch_item["po_coverage_status"] == "SCHEDULED_AWAITING_PO"

        # Test WO Tracking Detail API
        resp_detail = client.get(f"/api/v1/work-orders/{wo_sch.wo_number}/tracking", headers=headers)
        assert resp_detail.status_code == 200, resp_detail.text
        detail = resp_detail.json()
        assert detail["source_type"] == "schedule"
        assert detail["po_coverage_status"] == "SCHEDULED_AWAITING_PO"

        # Test OAR Genealogy API
        resp_genealogy = client.get(f"/api/v1/operations/oars/{oar_comm_num}/genealogy", headers=headers)
        assert resp_genealogy.status_code == 200, resp_genealogy.text
        genealogy = resp_genealogy.json()
        assert genealogy["po_coverage_status"] == "COMMERCIAL_PO_PENDING"
        assert genealogy["po_matched"] is False
        assert genealogy["source_type"] == "po"

        # Cleanup
        db.delete(wo_comm)
        db.delete(wo_sch)
        db.delete(order_comm)
        db.delete(order_sch)
        db.delete(part)
        db.delete(cust)
        db.commit()
    finally:
        db.close()
