"""
Quantity semantics regression suite -- proves the exact example from the spec and
that rejected quantity never becomes OK/good WIP/movable quantity, and that
"Yet to Produce" is not the same figure as WIP.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException

from app.core.database import Base
from app.models.order import Order, Part, Customer, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.services.production_service import ProductionService
from app.schemas.production import RecordStageProductionRequest
from app.services.seed_service import _seed_default_rejection_types

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    _seed_default_rejection_types(session)
    session.commit()
    yield session
    session.close()


def _make_wo(db, wo_number, target_qty, stages="F1 -> F2 -> DISPATCH"):
    customer = Customer(customer_code=f"C-{wo_number}", name="Test Customer")
    part = Part(part_number=f"P-{wo_number}", description="Test Part")
    db.add_all([customer, part])
    db.flush()
    order = Order(oar_number=f"OAR-{wo_number}", customer_id=customer.id, part_id=part.id, customer_po="PO-1",
                  po_qty=target_qty, max_batch_size=target_qty, status=OrderStatus.ACCEPT)
    db.add(order)
    db.flush()
    wo = WorkOrder(wo_number=wo_number, order_id=order.id, physical_wo_qty=target_qty,
                    current_stage="F1", projected_final_good=target_qty, status=WOStatus.IN_PRODUCTION)
    db.add(wo)
    db.flush()
    stage_list = [s.strip() for s in stages.split("->")]
    for seq, stg in enumerate(stage_list, start=1):
        db.add(WORoute(work_order_id=wo.id, stage=stg, sequence=seq, stage_target_qty=target_qty,
                        stage_status="In-Progress" if seq == 1 else "Pending"))
    db.add(StageWIP(work_order_id=wo.id, stage=stage_list[0], ent_qty=target_qty, ok_qty=0, inproc_qty=target_qty,
                     onhand_qty=0, rejected_qty=0, available_wip=target_qty))
    db.commit()
    db.refresh(wo)
    return wo


def test_produced_25_rejected_2_good_23_yet_to_produce_25(db):
    """Target = 50. Transaction: Produced = 25, Rejected = 2.
    Expected: Total Produced = 25, Total Rejected = 2, Total Good = 23, Yet to
    Produce = 25 (50 - 25, NOT reduced by the transaction's rejected count in a
    way that would double-subtract, and never merges rejected into good)."""
    wo = _make_wo(db, "WO-QTY-1", target_qty=50)

    req = RecordStageProductionRequest(wo_number="WO-QTY-1", stage="F1", good_qty=23, rejected_quantity=2, defect_code="DEF-POROSITY")
    res = ProductionService.record_stage_production(db, req)
    assert res.success is True
    assert res.good_qty == 23
    assert res.rejected_quantity == 2
    assert res.stage_ok_total == 23
    assert res.stage_rejection_total == 2

    dashboard = ProductionService.get_stage_dashboard(db, "WO-QTY-1", "F1")
    assert dashboard.target_qty == 50
    assert dashboard.total_produced == 25  # 23 good + 2 rejected
    assert dashboard.total_rejected == 2
    assert dashboard.total_good == 23
    assert dashboard.yet_to_produce == 25  # 50 - 25
    # Rejected quantity must never appear as movable/good WIP.
    assert dashboard.remaining_movable_qty == 23  # only the good pieces, sitting on-hand
    assert dashboard.wip_qty == 25  # inproc_qty = ent(50) - ok(23) - rej(2) = still-unconverted material


def test_partial_production_third_entry_exceeding_remaining_is_rejected(db):
    """Target = 10. First: Produced=5, Rejected=0. Second: Produced=5, Rejected=0.
    Third: Produced > remaining must be rejected by the backend."""
    _make_wo(db, "WO-QTY-2", target_qty=10)

    res1 = ProductionService.record_stage_production(
        db, RecordStageProductionRequest(wo_number="WO-QTY-2", stage="F1", good_qty=5, rejected_quantity=0)
    )
    assert res1.stage_ok_total == 5
    assert res1.stage_inproc_remaining == 5

    res2 = ProductionService.record_stage_production(
        db, RecordStageProductionRequest(wo_number="WO-QTY-2", stage="F1", good_qty=5, rejected_quantity=0)
    )
    assert res2.stage_ok_total == 10
    assert res2.stage_inproc_remaining == 0

    with pytest.raises(HTTPException) as exc:
        ProductionService.record_stage_production(
            db, RecordStageProductionRequest(wo_number="WO-QTY-2", stage="F1", good_qty=1, rejected_quantity=0)
        )
    assert exc.value.status_code == 400


def test_rejected_quantity_never_becomes_ok_good_or_movable(db):
    _make_wo(db, "WO-QTY-3", target_qty=20)
    res = ProductionService.record_stage_production(
        db, RecordStageProductionRequest(wo_number="WO-QTY-3", stage="F1", good_qty=10, rejected_quantity=5, defect_code="DEF-POROSITY")
    )
    assert res.stage_ok_total == 10  # rejected never added here
    assert res.stage_rejection_total == 5

    dashboard = ProductionService.get_stage_dashboard(db, "WO-QTY-3", "F1")
    assert dashboard.total_good == 10
    assert dashboard.remaining_movable_qty == 10  # the 5 rejected are excluded
    assert dashboard.wip_qty == 5  # inproc = ent(20) - ok(10) - rej(5) -- rejected reduces WIP, never adds to it


def test_yet_to_produce_is_not_the_same_as_wip_numerically_equal_case(db):
    """At a stage whose entered quantity already equals its full target, WIP
    (inproc_qty = ent - ok - rej) and Yet to Produce (target - ok - rej) happen to
    be numerically equal -- but they are computed from different fields/formulas,
    not aliased. The next test shows a case where they genuinely diverge."""
    _make_wo(db, "WO-QTY-4", target_qty=100)
    ProductionService.record_stage_production(
        db, RecordStageProductionRequest(wo_number="WO-QTY-4", stage="F1", good_qty=30, rejected_quantity=0)
    )
    dashboard = ProductionService.get_stage_dashboard(db, "WO-QTY-4", "F1")
    assert dashboard.yet_to_produce == 70  # 100 - 30
    assert dashboard.wip_qty == 70  # inproc = ent(100) - ok(30) - rej(0)


def test_yet_to_produce_diverges_from_wip_when_entered_qty_lags_target(db):
    """The real-world distinction: a downstream stage's target is fixed at release
    time, but material only physically arrives (StageWIP.ent_qty) as it's moved in
    from the upstream stage. Before anything has moved into F2, WIP (what's
    physically present) is 0 even though Yet to Produce (what's still owed against
    the overall target) is the full target -- proving the two are never conflated."""
    wo = _make_wo(db, "WO-QTY-5", target_qty=50, stages="F1 -> F2 -> DISPATCH")
    # F2's own route target is set independently of what has arrived there so far.
    f2_route = next(r for r in wo.routes if r.stage == "F2")
    f2_route.stage_target_qty = 50
    db.add(StageWIP(work_order_id=wo.id, stage="F2", ent_qty=0, ok_qty=0, inproc_qty=0,
                     onhand_qty=0, rejected_qty=0, available_wip=0))
    db.commit()

    dashboard = ProductionService.get_stage_dashboard(db, "WO-QTY-5", "F2")
    assert dashboard.wip_qty == 0  # nothing has physically arrived at F2 yet
    assert dashboard.yet_to_produce == 50  # still fully owed against F2's target
    assert dashboard.wip_qty != dashboard.yet_to_produce
