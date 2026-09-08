"""
VSPL SMES + OMS - Phase 2 Execution & Validation Test Suite
Tests dedicated stage production entry, physical movements, sequential routing,
idempotency, terminal stage protection, and complete end-to-end reconciliation.
"""

import pytest
import uuid
from datetime import datetime, date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.core.database import Base
from app.models.user import User, UserRole
from app.models.order import Order, Part, Customer, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.production import ProductionUpdate, ProductionStatus
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.nc import NCRecord

from app.services.production_service import ProductionService
from app.services.packing_service import PackingService
from app.services.dispatch_service import DispatchService
from app.services.work_order_service import WorkOrderService
from app.services.oms_integration_service import OMSIntegrationService

from app.schemas.production import (
    MovePartsRequest,
    RecordStageProductionRequest
)
from app.schemas.packing import PackingUpdateRequest
from app.schemas.dispatch import DispatchRequest
from app.analytics.math_engine import reconciliation_variance

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()

    cust = Customer(customer_code="CUST-PH2", name="Phase 2 Industrial Corp")
    part = Part(part_number="BRZ-PH2-BUSH", grade="PB2 / CuSn11P", description="High Precision Bushing")
    session.add(cust)
    session.add(part)
    session.commit()

    yield session
    session.close()


def create_phase2_order_and_wo(db, physical_wo_qty=100, route=None):
    cust = db.query(Customer).first()
    part = db.query(Part).first()

    order = Order(
        oar_number=f"OAR-PH2-{uuid.uuid4().hex[:6]}",
        customer_po="PO-PH2-001",
        customer_id=cust.id,
        part_id=part.id,
        po_qty=physical_wo_qty,
        max_batch_size=50,
        status=OrderStatus.ACCEPT,
        delivery_date=date.today()
    )
    db.add(order)
    db.commit()

    wo_number = f"WO-PH2-{uuid.uuid4().hex[:6]}"
    wo = WorkOrder(
        wo_number=wo_number,
        order_id=order.id,
        physical_wo_qty=physical_wo_qty,
        current_stage="F1",
        status=WOStatus.RELEASED,
        shortfall="No",
        projected_final_good=physical_wo_qty
    )
    db.add(wo)
    db.commit()

    actual_route = route or ["F1", "F2", "PACKING", "BSR", "DISPATCH"]
    OMSIntegrationService.initialize_wo_stages(db, wo, actual_route)

    return order, wo, actual_route


# ============================================================
# SCENARIO 29: Complete End-to-End Execution & Reconciliation
# ============================================================
def test_scenario_29_complete_execution_and_reconciliation(db):
    """
    Scenario 29:
    1. WO Released for 100 pcs on route F1 -> F2 -> PACKING -> BSR -> DISPATCH.
    2. F1 moves 50 pcs, then 50 pcs (F1 WIP = 0, F2 WIP = 100).
    3. F2 produces 50 OK (0 Rej), then 40 OK + 10 Rej (F2 OK = 90, F2 Rej = 10).
    4. F2 moves 90 pcs to PACKING.
    5. PACKING moves 90 pcs to BSR.
    6. BSR moves 90 pcs to DISPATCH.
    7. DISPATCH dispatches 90 pcs.
    8. Final: 90 Dispatched, 10 Scrapped, 0 WIP Remaining.
    9. Reconciliation variance = 0.
    """
    order, wo, route = create_phase2_order_and_wo(db, physical_wo_qty=100)

    # Step 1: F1 moves partial batch of 50 to F2
    res1 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number=wo.wo_number,
        from_stage="F1",
        to_stage="F2",
        quantity_moved=50,
        client_request_id="REQ-F1-01"
    ))
    assert res1.quantity_moved == 50
    assert res1.available_wip_remaining == 50
    assert res1.to_stage_available_wip == 50

    # Step 2: F1 moves remaining batch of 50 to F2
    res2 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number=wo.wo_number,
        from_stage="F1",
        to_stage="F2",
        quantity_moved=50,
        client_request_id="REQ-F1-02"
    ))
    assert res2.quantity_moved == 50
    assert res2.available_wip_remaining == 0
    assert res2.to_stage_available_wip == 100

    # Step 3: F2 logs production of 50 OK (0 Rej)
    prod1 = ProductionService.record_stage_production(db, RecordStageProductionRequest(
        wo_number=wo.wo_number,
        stage="F2",
        good_qty=50,
        rejected_quantity=0,
        machine_id="M-LATHE-01",
        operator_name="Operator Suresh",
        client_request_id="REQ-PROD-01"
    ))
    assert prod1.good_qty == 50
    assert prod1.stage_ok_total == 50
    assert prod1.stage_rejection_total == 0

    # Step 4: F2 logs production of 40 OK + 10 Rej
    prod2 = ProductionService.record_stage_production(db, RecordStageProductionRequest(
        wo_number=wo.wo_number,
        stage="F2",
        good_qty=40,
        rejected_quantity=10,
        machine_id="M-LATHE-01",
        defect_code="DEF-POROSITY",
        remarks="Gas porosity defect",
        operator_name="Operator Suresh",
        client_request_id="REQ-PROD-02"
    ))
    assert prod2.good_qty == 40
    assert prod2.rejected_quantity == 10
    assert prod2.stage_ok_total == 90
    assert prod2.stage_rejection_total == 10

    # Step 5: F2 transfers 90 OK parts to PACKING
    res3 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number=wo.wo_number,
        from_stage="F2",
        to_stage="PACKING",
        quantity_moved=90,
        client_request_id="REQ-F2-01"
    ))
    assert res3.quantity_moved == 90
    assert res3.available_wip_remaining == 0
    assert res3.to_stage_available_wip == 90

    # Step 6a: PACKING moves 90 to BSR
    res4 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number=wo.wo_number,
        from_stage="PACKING",
        to_stage="BSR",
        quantity_moved=90,
        client_request_id="REQ-PCK-01"
    ))
    assert res4.quantity_moved == 90
    assert res4.to_stage_available_wip == 90

    # Step 6b: Update Packing record
    pack_res = PackingService.update_packing(db, PackingUpdateRequest(
        wo_number=wo.wo_number,
        packed_quantity=90,
        box_count=2,
        packaging_type="Wooden Box",
        verified_by="QA Inspector"
    ))
    assert pack_res.packed_this_batch == 90
    assert pack_res.ready_for_dispatch == 90

    # Step 7: BSR moves 90 to DISPATCH
    res5 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number=wo.wo_number,
        from_stage="BSR",
        to_stage="DISPATCH",
        quantity_moved=90,
        client_request_id="REQ-BSR-01"
    ))
    assert res5.quantity_moved == 90

    # Step 8: DISPATCH dispatches 90 pcs
    disp = DispatchService.execute_dispatch(db, DispatchRequest(
        wo_number=wo.wo_number,
        dispatched_quantity=90,
        invoice_number="INV-PH2-90",
        vehicle_number="KA-01-9999",
        transporter_name="FastFreight Logistics"
    ))
    assert disp.dispatched_quantity == 90

    # Step 9: Verify Live Tracking and Balance
    tracking = WorkOrderService.get_tracking_detail(db, wo.wo_number)
    assert tracking.status == WOStatus.DISPATCHED.value
    assert tracking.physical_wo_qty == 100
    assert tracking.total_rejected == 10
    assert tracking.yield_pct == 90.0
    assert len(tracking.transactions) >= 6

    # Verify Mass Reconciliation
    variance = reconciliation_variance(
        released_qty=100,
        total_wip=0,
        dispatched_qty=90,
        total_scrap=10
    )
    assert variance == 0


# ============================================================
# SCENARIO 30: Invalid Tests & Guardrails
# ============================================================
def test_invalid_movement_excess_quantity(db):
    """Moving more than available WIP must fail with HTTP 400."""
    _, wo, _ = create_phase2_order_and_wo(db, physical_wo_qty=50)

    with pytest.raises(HTTPException) as exc:
        ProductionService.move_parts(db, MovePartsRequest(
            wo_number=wo.wo_number,
            from_stage="F1",
            to_stage="F2",
            quantity_moved=60, # Only 50 available
            client_request_id="REQ-ERR-01"
        ))
    assert exc.value.status_code == 400
    assert "available" in exc.value.detail.lower()


def test_invalid_stage_skipping(db):
    """Skipping a stage in the route (e.g. F1 -> PACKING) must fail with HTTP 400."""
    _, wo, _ = create_phase2_order_and_wo(db, physical_wo_qty=50)

    with pytest.raises(HTTPException) as exc:
        ProductionService.move_parts(db, MovePartsRequest(
            wo_number=wo.wo_number,
            from_stage="F1",
            to_stage="PACKING", # F2 is next, not PACKING
            quantity_moved=20,
            client_request_id="REQ-SKIP-01"
        ))
    assert exc.value.status_code == 400
    assert "invalid stage sequence" in exc.value.detail.lower() or "cannot jump" in exc.value.detail.lower()


def test_invalid_terminal_stage_movement(db):
    """Moving out of terminal stage DISPATCH must fail with HTTP 400."""
    _, wo, _ = create_phase2_order_and_wo(db, physical_wo_qty=50)

    # Set WO stage to DISPATCH
    wo.current_stage = "DISPATCH"
    db.commit()

    with pytest.raises(HTTPException) as exc:
        ProductionService.move_parts(db, MovePartsRequest(
            wo_number=wo.wo_number,
            from_stage="DISPATCH",
            to_stage="CLOSED",
            quantity_moved=10,
            client_request_id="REQ-TERM-01"
        ))
    assert exc.value.status_code == 400


def test_movement_idempotency(db):
    """Duplicate client_request_id must return existing transaction without double deduction."""
    _, wo, _ = create_phase2_order_and_wo(db, physical_wo_qty=50)

    req_id = "REQ-IDEMP-TEST-01"
    res1 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number=wo.wo_number,
        from_stage="F1",
        to_stage="F2",
        quantity_moved=20,
        client_request_id=req_id
    ))
    assert res1.quantity_moved == 20
    assert res1.available_wip_remaining == 30

    # Submit same request ID again
    res2 = ProductionService.move_parts(db, MovePartsRequest(
        wo_number=wo.wo_number,
        from_stage="F1",
        to_stage="F2",
        quantity_moved=20,
        client_request_id=req_id
    ))
    # Must match original movement ID and not reduce WIP again
    assert res2.movement_id == res1.movement_id
    assert res2.available_wip_remaining == 30


def test_production_entry_idempotency(db):
    """Duplicate client_request_id for production entry must return existing entry without double counting."""
    _, wo, _ = create_phase2_order_and_wo(db, physical_wo_qty=50)

    req_id = "REQ-PROD-IDEMP-01"
    res1 = ProductionService.record_stage_production(db, RecordStageProductionRequest(
        wo_number=wo.wo_number,
        stage="F1",
        good_qty=20,
        rejected_quantity=2,
        client_request_id=req_id
    ))
    assert res1.good_qty == 20
    assert res1.stage_ok_total == 20

    # Submit same request ID again
    res2 = ProductionService.record_stage_production(db, RecordStageProductionRequest(
        wo_number=wo.wo_number,
        stage="F1",
        good_qty=20,
        rejected_quantity=2,
        client_request_id=req_id
    ))
    assert res2.entry_id == res1.entry_id
    assert res2.stage_ok_total == 20


def test_production_entry_excess_quantity(db):
    """Logging production with (good + rejected) exceeding stage in-process WIP must fail."""
    _, wo, _ = create_phase2_order_and_wo(db, physical_wo_qty=30)

    with pytest.raises(HTTPException) as exc:
        ProductionService.record_stage_production(db, RecordStageProductionRequest(
            wo_number=wo.wo_number,
            stage="F1",
            good_qty=25,
            rejected_quantity=10, # 25 + 10 = 35 > 30
            client_request_id="REQ-PROD-EXCESS"
        ))
    assert exc.value.status_code == 400
    assert "available at stage" in exc.value.detail.lower() or "cannot process" in exc.value.detail.lower()
