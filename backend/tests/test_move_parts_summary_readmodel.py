"""Regression tests for the Move Parts production/movement summary read-model
(OMSIntegrationService.get_current_stage_state).

This is a visibility-only addition: `already_moved_qty` is a derived read value
(= ok_qty - onhand_qty, both already-authoritative StageWIP fields), not a new
calculation system, and no mutation behavior or production/movement semantics
changed. These tests only prove the READ-MODEL values are correct and stage-isolated
-- the write-path correctness (overposting, partial production/movement, concurrency)
is already covered by test_production_overpost_fix.py.
"""
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services.seed_service import seed_database_if_empty
from app.services.operations_service import OperationsService
from app.services.production_service import ProductionService
from app.services.oms_integration_service import OMSIntegrationService
from app.schemas.operations import OrderIntakeCreate
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest
from app.models.work_order import WorkOrder

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


def _fresh_wo(db, po_qty=100):
    res = OperationsService.create_order_intake(db, OrderIntakeCreate(
        customer_code=f"CUST-{uuid.uuid4().hex[:6]}", customer_name="Summary Test Co",
        customer_po=f"PO-{uuid.uuid4().hex[:8]}", part_number=f"PART-{uuid.uuid4().hex[:6]}",
        po_quantity=po_qty, max_batch_size=po_qty
    ))
    return res.wos_created[0]


def _state(db, wo_num, stage="F1"):
    wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
    return OMSIntegrationService.get_current_stage_state(db, wo, stage)


# ---------------------------------------------------------------------------
# 1. No production -- STATE A
# ---------------------------------------------------------------------------

def test_state_a_no_production(db_session):
    """A freshly-released WO's first stage starts with its full released quantity as
    raw, unprocessed material (in_process_qty) -- this is the existing, unchanged
    combined process+move ceiling (available_wip = in_process + on_hand), not
    something this read-model addition changes. OK/Rejected/Already-Moved are what's
    new here to distinguish, and they are correctly all zero."""
    wo = _fresh_wo(db_session, po_qty=100)
    s = _state(db_session, wo)
    assert s["ok_completed_qty"] == 0
    assert s["rejected_qty"] == 0
    assert s["already_moved_qty"] == 0
    assert s["in_process_qty"] == 100
    assert s["available_wip"] == 100


# ---------------------------------------------------------------------------
# 2. Partial production -- STATE B
# ---------------------------------------------------------------------------

def test_state_b_partial_production(db_session):
    """Before any movement, available_wip (100) still includes the 50 still-unprocessed
    units (in_process_qty) under the existing combined process+move ceiling -- this
    read-model addition's job is to also expose OK (50) and Already Moved (0)
    distinctly, not to change that ceiling."""
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    s = _state(db_session, wo)
    assert s["ok_completed_qty"] == 50
    assert s["rejected_qty"] == 0
    assert s["already_moved_qty"] == 0
    assert s["in_process_qty"] == 50
    assert s["available_wip"] == 100


# ---------------------------------------------------------------------------
# 3. Production + rejection
# ---------------------------------------------------------------------------

def test_production_plus_rejection_shown_separately(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=5, defect_code="DEF-POROSITY"
    ))
    s = _state(db_session, wo)
    assert s["ok_completed_qty"] == 50
    assert s["rejected_qty"] == 5
    # The 5 rejected pieces are permanently excluded from the ceiling: of the 100
    # released, 5 are gone (rejected) and the remaining 95 (45 still-unprocessed +
    # 50 completed on-hand) is the full available_wip -- rejected quantity never
    # re-enters the movable pool.
    assert s["available_wip"] == 95
    assert s["in_process_qty"] == 45
    assert s["on_hand_qty"] == 50


# ---------------------------------------------------------------------------
# 4-5. Partial movement / full movement -- STATE C
# ---------------------------------------------------------------------------

def test_state_c_after_full_movement_of_produced_quantity(db_session):
    """After moving exactly what was produced, on_hand drops to 0 and already_moved
    equals the full OK quantity. available_wip (50) is not 0 here -- 50 pieces of the
    100-unit target remain genuinely unprocessed (in_process_qty), which is a distinct,
    separately-displayed "Remaining to Produce" figure, not conflated with "already
    moved". This is the existing, already-tested combined process+move ceiling
    (test_part_41_exact_business_scenario) -- unchanged by this read-model addition."""
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=50, rejected_quantity=0
    ))
    s = _state(db_session, wo)
    assert s["ok_completed_qty"] == 50
    assert s["already_moved_qty"] == 50
    assert s["on_hand_qty"] == 0
    assert s["in_process_qty"] == 50
    assert s["available_wip"] == 50


def test_partial_movement_leaves_remaining_available(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=80, rejected_quantity=0
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=30, rejected_quantity=0
    ))
    s = _state(db_session, wo)
    assert s["ok_completed_qty"] == 80
    assert s["already_moved_qty"] == 30
    # available_wip = in_process (20 still-unprocessed of the 100 released) + onhand
    # (50 completed-but-not-yet-moved, i.e. the 80 produced minus the 30 already moved)
    assert s["in_process_qty"] == 20
    assert s["available_wip"] == 70


# ---------------------------------------------------------------------------
# 6. Additional production after movement -- STATE D
# ---------------------------------------------------------------------------

def test_state_d_additional_production_after_movement(db_session):
    """Second entry is 45 OK + 5 Reject (not 50 OK + 5 Reject) because OK and Reject
    share the same authoritative target pool (ent_qty - ok - rejected =
    in_process_qty), per the existing OMS Engine rule already enforced and verified in
    test_production_overpost_fix.py -- 50 (first entry) + 50 (second entry) would be
    100 processed already, leaving no room for +5 more rejected on top."""
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=50, rejected_quantity=0
    ))
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=45, rejected_quantity=5, defect_code="DEF-POROSITY"
    ))
    s = _state(db_session, wo)
    assert s["ok_completed_qty"] == 95
    assert s["rejected_qty"] == 5
    assert s["already_moved_qty"] == 50
    assert s["available_wip"] == 45
    assert s["in_process_qty"] == 0


# ---------------------------------------------------------------------------
# 7. Multiple movements
# ---------------------------------------------------------------------------

def test_multiple_movements_accumulate_already_moved(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=100, rejected_quantity=0
    ))
    for qty in (20, 30, 25):
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=qty, rejected_quantity=0
        ))
    s = _state(db_session, wo)
    assert s["already_moved_qty"] == 75
    assert s["on_hand_qty"] == 25
    assert s["available_wip"] == 25


# ---------------------------------------------------------------------------
# 8. Rejection never shown as movable good WIP
# ---------------------------------------------------------------------------

def test_rejection_never_counted_as_movable(db_session):
    wo = _fresh_wo(db_session, po_qty=50)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=0, rejected_quantity=50, defect_code="DEF-POROSITY"
    ))
    s = _state(db_session, wo)
    assert s["ok_completed_qty"] == 0
    assert s["rejected_qty"] == 50
    assert s["available_wip"] == 0
    assert s["already_moved_qty"] == 0


# ---------------------------------------------------------------------------
# 9. Cross-stage values remain isolated
# ---------------------------------------------------------------------------

def test_cross_stage_values_remain_isolated(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=100, rejected_quantity=0
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=100, rejected_quantity=0
    ))
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F2", good_qty=40, rejected_quantity=10, defect_code="DEF-POROSITY"
    ))

    f1 = _state(db_session, wo, "F1")
    f2 = _state(db_session, wo, "F2")

    assert f1["ok_completed_qty"] == 100
    assert f1["already_moved_qty"] == 100
    assert f1["available_wip"] == 0

    assert f2["ok_completed_qty"] == 40
    assert f2["rejected_qty"] == 10
    assert f2["already_moved_qty"] == 0
    # F2 received 100 (ent_qty), produced 40 OK + 10 rejected so far -- its own
    # available_wip (in_process 50 + on_hand 40 = 90) is entirely independent of F1's
    # (0), proving the two stages' figures are never conflated.
    assert f2["available_wip"] == 90, "F2's own movable WIP must not be conflated with F1's"


# ---------------------------------------------------------------------------
# 10. Zero-WIP state remains correctly blocked
# ---------------------------------------------------------------------------

def test_zero_wip_state_blocks_movement(db_session):
    from fastapi import HTTPException
    wo = _fresh_wo(db_session, po_qty=30)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=0, rejected_quantity=30, defect_code="DEF-POROSITY"
    ))
    s = _state(db_session, wo)
    assert s["available_wip"] == 0

    with pytest.raises(HTTPException):
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=1, rejected_quantity=0
        ))
