"""Regression tests for:
  - OAR -> WO quantity split (equal/manual allocation, validation, atomicity)
  - Production -> StageWIP correctness (fresh delta, rejected never movable)
  - StageWIP -> Move Parts eligibility (movable WIP only, route/cross-WO/idempotency)
  - The WO-1004-style root cause scenario end to end

Uses the same in-memory-SQLite + seeded-session pattern as
tests/test_oms_smes_integration.py so it participates in the existing suite unchanged.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services.seed_service import seed_database_if_empty
from app.services.operations_service import OperationsService
from app.services.production_service import ProductionService
from app.schemas.operations import OrderIntakeCreate, WOReleaseCreate
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest
from app.models.order import Order, Customer
from app.models.work_order import WorkOrder
from app.models.production_movement import StageWIP

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    seed_database_if_empty(session)
    yield session
    session.close()


# --------------------------------------------------------------------------
# OAR -> WO quantity split
# --------------------------------------------------------------------------

def test_auto_split_equal_with_remainder(db_session):
    """100 qty / batch 33 -> ceil(100/33)=4 WOs: 33, 33, 33, 1 (deterministic remainder)."""
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-SPLIT", customer_name="Split Co", customer_po="PO-SPLIT-AUTO",
        part_number="PART-SPLIT-AUTO", po_quantity=100, max_batch_size=33
    ))
    assert res.wo_quantities == [33, 33, 33, 1]
    assert sum(res.wo_quantities) == 100
    assert len(res.wos_created) == 4

def test_manual_split_unequal(db_session):
    """Explicit unequal split 400/300/200/100 must be honored exactly, in order."""
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-SPLIT", customer_name="Split Co", customer_po="PO-SPLIT-MANUAL",
        part_number="PART-SPLIT-MANUAL", po_quantity=1000, max_batch_size=1000,
        wo_quantities=[400, 300, 200, 100]
    ))
    assert res.wo_quantities == [400, 300, 200, 100]
    assert len(res.wos_created) == 4

    wos = db_session.query(WorkOrder).filter(WorkOrder.wo_number.in_(res.wos_created)).all()
    by_number = {w.wo_number: w.physical_wo_qty for w in wos}
    for wo_num, qty in zip(res.wos_created, res.wo_quantities):
        assert by_number[wo_num] == qty

def test_manual_split_over_allocation_rejected(db_session):
    """400+300+200+200=1100 vs po_quantity=1000 must be rejected, not silently accepted."""
    with pytest.raises(HTTPException) as exc:
        OperationsService.create_order_intake(db_session, OrderIntakeCreate(
            customer_code="CUST-SPLIT", customer_name="Split Co", customer_po="PO-SPLIT-OVER",
            part_number="PART-SPLIT-OVER", po_quantity=1000, max_batch_size=1000,
            wo_quantities=[400, 300, 200, 200]
        ))
    assert exc.value.status_code == 400

def test_manual_split_under_allocation_rejected(db_session):
    """400+300+200=900 vs po_quantity=1000 must be rejected."""
    with pytest.raises(HTTPException) as exc:
        OperationsService.create_order_intake(db_session, OrderIntakeCreate(
            customer_code="CUST-SPLIT", customer_name="Split Co", customer_po="PO-SPLIT-UNDER",
            part_number="PART-SPLIT-UNDER", po_quantity=1000, max_batch_size=1000,
            wo_quantities=[400, 300, 200]
        ))
    assert exc.value.status_code == 400

def test_manual_split_zero_quantity_rejected(db_session):
    with pytest.raises(HTTPException) as exc:
        OperationsService.create_order_intake(db_session, OrderIntakeCreate(
            customer_code="CUST-SPLIT", customer_name="Split Co", customer_po="PO-SPLIT-ZERO",
            part_number="PART-SPLIT-ZERO", po_quantity=1000, max_batch_size=1000,
            wo_quantities=[0, 500, 500]
        ))
    assert exc.value.status_code == 400

def test_manual_split_negative_quantity_rejected(db_session):
    with pytest.raises(HTTPException) as exc:
        OperationsService.create_order_intake(db_session, OrderIntakeCreate(
            customer_code="CUST-SPLIT", customer_name="Split Co", customer_po="PO-SPLIT-NEG",
            part_number="PART-SPLIT-NEG", po_quantity=1000, max_batch_size=1000,
            wo_quantities=[-100, 600, 500]
        ))
    assert exc.value.status_code == 400

def test_rejected_split_creates_no_partial_rows(db_session):
    """An invalid split must fail atomically before any Customer/Part/Order row exists --
    no orphaned OAR left behind."""
    with pytest.raises(HTTPException):
        OperationsService.create_order_intake(db_session, OrderIntakeCreate(
            customer_code="CUST-ATOMIC", customer_name="Atomic Co", customer_po="PO-ATOMIC-1",
            part_number="PART-ATOMIC", po_quantity=1000, max_batch_size=1000,
            wo_quantities=[999, 999]  # sums to 1998, way over
        ))
    assert db_session.query(Customer).filter(Customer.customer_code == "CUST-ATOMIC").first() is None
    assert db_session.query(Order).filter(Order.customer_po == "PO-ATOMIC-1").first() is None

def test_oar_wo_relationship_sum_matches(db_session):
    """Sum of every created WO's quantity must equal the OAR quantity, and each WO
    must be linked to the correct order."""
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-REL", customer_name="Relation Co", customer_po="PO-REL-1",
        part_number="PART-REL", po_quantity=750, max_batch_size=750,
        wo_quantities=[250, 250, 250]
    ))
    order = db_session.query(Order).filter(Order.oar_number == res.oar_number).first()
    wos = db_session.query(WorkOrder).filter(WorkOrder.order_id == order.id).all()
    assert sum(w.physical_wo_qty for w in wos) == order.po_qty == 750
    assert {w.wo_number for w in wos} == set(res.wos_created)


# --------------------------------------------------------------------------
# Production -> StageWIP -> Move eligibility (the WO-1004 root cause scenario)
# --------------------------------------------------------------------------

def test_production_ok_and_rejected_tracked_separately(db_session):
    """OK and rejected are tracked as separate cumulative counters at the stage, and
    rejected pieces are permanently excluded from the movable-WIP ceiling (available_wip
    = inproc + onhand, where inproc = max(ent - ok - rej, 0) -- the existing OMS Engine
    formula). Rejecting 40 of 100 pieces must shrink available_wip by exactly 40, proving
    rejected quantity never re-enters the movable pool."""
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-PROD", customer_name="Prod Co", customer_po="PO-PROD-1",
        part_number="PART-PROD", po_quantity=100, max_batch_size=100
    ))
    wo_num = res.wos_created[0]

    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo_num, stage="F1", good_qty=0, rejected_quantity=40
    ))

    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
    wip = db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == "F1").first()
    assert wip.ok_qty == 0
    assert wip.rejected_qty == 40
    assert wip.available_wip == 60, "Rejected quantity must be excluded from the movable-WIP ceiling"
    assert wip.available_wip + wip.rejected_qty == wip.ent_qty

def test_move_blocked_when_zero_movable_wip(db_session):
    """A WO with genuinely zero movable WIP must be blocked from moving -- this is
    CORRECT behavior, not a defect, when production/WIP is actually zero."""
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-BLOCK", customer_name="Block Co", customer_po="PO-BLOCK-1",
        part_number="PART-BLOCK", po_quantity=50, max_batch_size=50
    ))
    wo_num = res.wos_created[0]
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo_num, stage="F1", good_qty=0, rejected_quantity=50
    ))
    with pytest.raises(HTTPException):
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo_num, from_stage="F1", to_stage="F2", quantity_moved=1, rejected_quantity=0
        ))

def test_move_qty_exceeding_available_wip_rejected(db_session):
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-EXCEED", customer_name="Exceed Co", customer_po="PO-EXCEED-1",
        part_number="PART-EXCEED", po_quantity=50, max_batch_size=50
    ))
    wo_num = res.wos_created[0]
    with pytest.raises(HTTPException):
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo_num, from_stage="F1", to_stage="F2", quantity_moved=51, rejected_quantity=0
        ))

def test_cross_wo_movement_rejected(db_session):
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-XWO", customer_name="Cross Co", customer_po="PO-XWO-1",
        part_number="PART-XWO", po_quantity=100, max_batch_size=50,
        wo_quantities=[50, 50]
    ))
    wo_a, wo_b = res.wos_created
    with pytest.raises(HTTPException):
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo_a, target_wo_number=wo_b,
            from_stage="F1", to_stage="F2", quantity_moved=10, rejected_quantity=0
        ))

def test_stage_skip_rejected(db_session):
    """Moving from F1 directly to F3 (skipping F2) must be rejected -- sequential-only route."""
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-SKIP", customer_name="Skip Co", customer_po="PO-SKIP-1",
        part_number="PART-SKIP", po_quantity=50, max_batch_size=50
    ))
    wo_num = res.wos_created[0]
    with pytest.raises(HTTPException):
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo_num, from_stage="F1", to_stage="F3", quantity_moved=10, rejected_quantity=0
        ))

def test_movement_idempotent_via_client_request_id(db_session):
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-IDEM", customer_name="Idem Co", customer_po="PO-IDEM-1",
        part_number="PART-IDEM", po_quantity=50, max_batch_size=50
    ))
    wo_num = res.wos_created[0]
    req = MovePartsRequest(
        wo_number=wo_num, from_stage="F1", to_stage="F2",
        quantity_moved=20, rejected_quantity=0, client_request_id="idem-token-1"
    )
    first = ProductionService.move_parts(db_session, req)
    second = ProductionService.move_parts(db_session, req)
    assert first.movement_id == second.movement_id
    assert second.available_wip_remaining == first.available_wip_remaining

def test_wo_1004_style_root_cause_scenario(db_session):
    """OAR 100 -> WO-A=60/WO-B=40 -> release WO-A on F1->F2->FI->PACKING->DISPATCH ->
    two production entries at F1 (OK=30/Rej=2, then OK=20/Rej=1).

    Cumulative OK (50) and Rejected (3) must match exactly, proving fresh-delta entries
    accumulate correctly rather than overwriting. available_wip (57) is higher than OK
    (50) by exactly the still-unprocessed remainder (60 - 50 - 3 = 7 pieces physically
    at F1 that have not yet been dispositioned) -- under this WO's existing, tested
    "combined process + move" design (see test_part_41_exact_business_scenario in
    test_manufacturing_execution.py), that remainder is still part of the movable
    ceiling because moving it forward implicitly completes it as OK. What must NOT
    happen -- and what this test guards against -- is the 3 rejected pieces ever
    re-entering the movable pool: available_wip + rejected_qty must never exceed ent_qty.
    """
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-1004", customer_name="KSB Pumps & Valves Ltd", customer_po="PO-1004-TEST",
        part_number="BRZ-RING-250", po_quantity=100, max_batch_size=100,
        wo_quantities=[60, 40]
    ))
    wo_a, _wo_b = res.wos_created

    OperationsService.release_work_order(db_session, WOReleaseCreate(
        wo_number=wo_a, physical_wo_qty=60,
        route_stages=["F1", "F2", "FI", "PACKING", "DISPATCH"]
    ))

    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo_a, stage="F1", good_qty=30, rejected_quantity=2
    ))
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo_a, stage="F1", good_qty=20, rejected_quantity=1
    ))

    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_a).first()
    f1 = db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == "F1").first()
    assert f1.ok_qty == 50
    assert f1.rejected_qty == 3
    assert f1.available_wip == 57
    assert f1.available_wip + f1.rejected_qty == f1.ent_qty

    mov1 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_a, from_stage="F1", to_stage="F2", quantity_moved=30, rejected_quantity=0
    ))
    assert mov1.available_wip_remaining == 27
    assert mov1.to_stage_available_wip == 30

    mov2 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_a, from_stage="F1", to_stage="F2", quantity_moved=20, rejected_quantity=0
    ))
    assert mov2.available_wip_remaining == 7
    assert mov2.to_stage_available_wip == 50
