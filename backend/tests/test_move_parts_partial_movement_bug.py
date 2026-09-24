"""Regression tests for the "partial material movement cannot be completed" bug.

ROOT CAUSE (see WorkOrderService.get_tracking_detail / OMSIntegrationService.recompute_work_order):
`wo.current_stage` is the OMS "furthest stage touched" snapshot -- it advances to the
next route stage the instant that stage receives ANY quantity (ent_qty > 0), even while
the prior stage still has movable WIP sitting available (onhand_qty > 0). The Move Parts
screen used `wo.current_stage`/`available_wip` (which is looked up AT wo.current_stage)
as the movement source stage. After a partial move (e.g. 25 available -> move 15), F2's
ent_qty becomes > 0, `wo.current_stage` flips to F2, and the Move Parts screen then reads
F2's (usually zero, unprocessed) available_wip instead of F1's still-available 10 pieces --
making the still-legitimate second F1 -> F2 movement invisible.

The fix adds `movable_from_stage` / `movable_to_stage` / `movable_wip` to
WorkOrderTrackingDetail: the earliest route stage (by sequence) that still has
available_wip > 0. This reuses the exact same StageWIP.available_wip values already
computed by the existing OMS Engine -- no new quantity formula, no change to
`wo.current_stage`'s existing meaning (still used, unchanged, everywhere else: WO list
badges, dashboards, delivery-risk calculation, RAG status).
"""
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services.seed_service import seed_database_if_empty
from app.services.operations_service import OperationsService
from app.services.production_service import ProductionService
from app.services.work_order_service import WorkOrderService
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


def _fresh_wo(db, po_qty=25):
    res = OperationsService.create_order_intake(db, OrderIntakeCreate(
        customer_code=f"CUST-{uuid.uuid4().hex[:6]}", customer_name="Partial Move Test Co",
        customer_po=f"PO-{uuid.uuid4().hex[:8]}", part_number=f"PART-{uuid.uuid4().hex[:6]}",
        po_quantity=po_qty, max_batch_size=po_qty
    ))
    return res.wos_created[0]


def _tracking(db, wo_num):
    return WorkOrderService.get_tracking_detail(db, wo_num)


def _stage_state(db, wo_num, stage):
    wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
    return OMSIntegrationService.get_current_stage_state(db, wo, stage)


# ---------------------------------------------------------------------------
# TEST 1: 25 available, move 15 -> remaining 10, movement option stays available
# ---------------------------------------------------------------------------

def test_partial_movement_still_exposes_source_stage_as_movable(db_session):
    wo = _fresh_wo(db_session, po_qty=25)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=25, rejected_quantity=0
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=15, rejected_quantity=0
    ))

    t = _tracking(db_session, wo)

    # The bug: current_stage (furthest-touched) has already advanced to F2 because F2
    # now has ent_qty > 0 -- this is documented, existing, correct behavior for that
    # field and must NOT change.
    assert t.current_stage == "F2"

    # The fix: movable_from_stage must still correctly point back at F1, which has the
    # remaining 10 pieces the Move Parts screen must offer to move next.
    assert t.movable_from_stage == "F1"
    assert t.movable_to_stage == "F2"
    assert t.movable_wip == 10


# ---------------------------------------------------------------------------
# TEST 2: 25 available, move 15, then move 10 -> remaining 0 (the exact reported scenario)
# ---------------------------------------------------------------------------

def test_second_partial_movement_using_movable_fields_succeeds(db_session):
    wo = _fresh_wo(db_session, po_qty=25)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=25, rejected_quantity=0
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=15, rejected_quantity=0
    ))

    t = _tracking(db_session, wo)
    assert t.movable_from_stage == "F1"
    assert t.movable_wip == 10

    # This is exactly what the Move Parts screen now does: submit the SECOND movement
    # using movable_from_stage/movable_to_stage, not the (already-advanced) current_stage.
    res = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage=t.movable_from_stage, to_stage=t.movable_to_stage,
        quantity_moved=t.movable_wip, rejected_quantity=0
    ))
    assert res.success
    assert res.available_wip_remaining == 0

    f1 = _stage_state(db_session, wo, "F1")
    assert f1["available_wip"] == 0
    assert f1["already_moved_qty"] == 25

    t2 = _tracking(db_session, wo)
    # F1 is now fully drained -- it must no longer be offered as a movement source.
    assert t2.movable_from_stage != "F1"


# ---------------------------------------------------------------------------
# TEST 3: 25 available, move 10, move 10, move 5 -> remaining 0
# ---------------------------------------------------------------------------

def test_three_sequential_partial_movements_drain_exactly(db_session):
    wo = _fresh_wo(db_session, po_qty=25)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=25, rejected_quantity=0
    ))
    for qty in (10, 10, 5):
        t = _tracking(db_session, wo)
        assert t.movable_from_stage == "F1", f"F1 must remain the movable source before moving {qty}"
        assert t.movable_wip >= qty
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo, from_stage=t.movable_from_stage, to_stage=t.movable_to_stage,
            quantity_moved=qty, rejected_quantity=0
        ))

    f1 = _stage_state(db_session, wo, "F1")
    assert f1["available_wip"] == 0
    assert f1["already_moved_qty"] == 25


# ---------------------------------------------------------------------------
# TEST 4: attempt to move more than available is rejected
# ---------------------------------------------------------------------------

def test_overmove_rejected(db_session):
    wo = _fresh_wo(db_session, po_qty=25)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=25, rejected_quantity=0
    ))
    with pytest.raises(HTTPException) as exc:
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=26, rejected_quantity=0
        ))
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# TEST 5: move the full available quantity in one transaction -> disabled afterward
# ---------------------------------------------------------------------------

def test_full_single_movement_disables_source_afterward(db_session):
    wo = _fresh_wo(db_session, po_qty=25)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=25, rejected_quantity=0
    ))
    res = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=25, rejected_quantity=0
    ))
    assert res.available_wip_remaining == 0

    f1 = _stage_state(db_session, wo, "F1")
    assert f1["available_wip"] == 0

    t = _tracking(db_session, wo)
    assert t.movable_from_stage != "F1"


# ---------------------------------------------------------------------------
# TEST 6: two consecutive movements from the same source/destination pair both succeed
# (already covered functionally by TEST 2/3, this asserts the F2 -> F3 leg too)
# ---------------------------------------------------------------------------

def test_repeated_movement_same_route_pair_f2_to_f3(db_session):
    wo = _fresh_wo(db_session, po_qty=25)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=25, rejected_quantity=0
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=25, rejected_quantity=0
    ))
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F2", good_qty=25, rejected_quantity=0
    ))

    t = _tracking(db_session, wo)
    assert t.movable_from_stage == "F2"
    assert t.movable_to_stage == "F3"
    assert t.movable_wip == 25

    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F2", to_stage="F3", quantity_moved=15, rejected_quantity=0
    ))
    t2 = _tracking(db_session, wo)
    assert t2.movable_from_stage == "F2"
    assert t2.movable_wip == 10

    res = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F2", to_stage="F3", quantity_moved=10, rejected_quantity=0
    ))
    assert res.available_wip_remaining == 0


# ---------------------------------------------------------------------------
# TEST 7: state persists correctly across independent re-reads ("refresh the page")
# ---------------------------------------------------------------------------

def test_movable_state_is_recomputed_fresh_on_each_read(db_session):
    wo = _fresh_wo(db_session, po_qty=25)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=25, rejected_quantity=0
    ))
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=15, rejected_quantity=0
    ))

    # Simulate a browser refresh: read tracking detail twice independently, both must
    # agree -- there is no client-side or session-local cache involved.
    t_a = _tracking(db_session, wo)
    t_b = _tracking(db_session, wo)
    assert t_a.movable_from_stage == t_b.movable_from_stage == "F1"
    assert t_a.movable_wip == t_b.movable_wip == 10


# ---------------------------------------------------------------------------
# Cumulative production quantity must never be confused with a movement delta
# ---------------------------------------------------------------------------

def test_movement_quantity_is_independent_delta_not_cumulative(db_session):
    wo = _fresh_wo(db_session, po_qty=25)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=25, rejected_quantity=0
    ))
    r1 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=15, rejected_quantity=0
    ))
    r2 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=10, rejected_quantity=0
    ))
    # Each movement's own quantity_moved reflects only its own delta, never the running total.
    assert r1.quantity_moved == 15
    assert r2.quantity_moved == 10
    assert r1.movement_id != r2.movement_id
