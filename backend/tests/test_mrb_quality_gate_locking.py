import pytest
import uuid
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, auto_migrate_schema
from app.models.order import Customer, Part, Order
from app.models.work_order import WorkOrder, WOStatus
from app.models.production_movement import StageWIP, ProductionMovement
from app.models.mrb import MRBReview
from app.models.user import User
from app.services.production_service import ProductionService
from app.services.mrb_service import MRBService
from app.services.oms_integration_service import OMSIntegrationService
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest
from app.schemas.mrb import MRBReviewDecisionRequest


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    auto_migrate_schema()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _setup_test_wo(db: Session, qty: int = 100):

    unique = uuid.uuid4().hex[:6]
    cust = Customer(customer_code=f"CUST-{unique}", name=f"Test Customer {unique}", is_active=True)
    part = Part(part_number=f"PART-{unique}", description=f"Test Part {unique}")
    db.add_all([cust, part])

    db.flush()

    order = Order(
        customer_id=cust.id,
        part_id=part.id,
        oar_number=f"OAR-{unique}",
        customer_po=f"PO-{unique}",
        po_qty=qty,
        status="ACCEPT"
    )
    db.add(order)

    db.flush()

    wo = WorkOrder(
        order_id=order.id,
        wo_number=f"WO-MRB-{unique}",
        physical_wo_qty=qty,
        status=WOStatus.RELEASED,
        current_stage="F1"
    )
    db.add(wo)
    db.flush()

    # Route: F1 -> F2 -> F3 -> FI -> PACKING -> DISPATCH
    OMSIntegrationService.initialize_wo_stages(db, wo, "F1 -> F2 -> F3 -> FI -> PACKING -> DISPATCH")
    db.commit()
    return wo


def test_mrb_quality_gate_blocks_movement_until_approval(db):
    """Option 2: Material cannot move to the next gate until Quality/Planner approves in MRB."""
    wo = _setup_test_wo(db, qty=100)

    # 1. Floor operator records production: 50 OK, 0 Rejected at F1
    prod_res = ProductionService.record_stage_production(
        db,
        RecordStageProductionRequest(
            wo_number=wo.wo_number,
            stage="F1",
            good_qty=50,
            rejected_quantity=0,
            operator_name="Operator Suresh"
        )
    )
    assert prod_res.success is True

    # 2. Verify that an MRB review ticket was created with status PENDING
    mrb_ticket = db.query(MRBReview).filter(
        MRBReview.work_order_id == wo.id,
        MRBReview.stage == "F1"
    ).first()
    assert mrb_ticket is not None
    assert mrb_ticket.status == "PENDING"
    assert mrb_ticket.reported_ok_qty == 50

    # 3. Check stage state: movement must report LOCKED
    state = OMSIntegrationService.get_current_stage_state(db, wo, "F1")
    assert state["mrb_lock_status"] == "LOCKED"
    assert state["mrb_approved_movable_qty"] == 0
    assert state["mrb_pending_qty"] == 50
    assert mrb_ticket.mrb_number in state["pending_mrb_tickets"]

    # 4. Attempting to move parts without MRB approval MUST be blocked with HTTP 400
    with pytest.raises(HTTPException) as exc_info:
        ProductionService.move_parts(
            db,
            MovePartsRequest(
                wo_number=wo.wo_number,
                from_stage="F1",
                to_stage="F2",
                quantity_moved=50
            )
        )
    assert exc_info.value.status_code == 400
    assert "Movement locked" in exc_info.value.detail
    assert "Material Review Board" in exc_info.value.detail

    # 5. Quality / Planner reviews and APPROVES the MRB ticket
    quality_user = User(
        id=uuid.uuid4(),
        email=f"quality-{uuid.uuid4().hex[:6]}@vspl.com",
        full_name="Quality Inspector Vikram",
        hashed_password="mockhashedpassword",
        role="QA",
        is_active=True
    )

    db.add(quality_user)
    db.commit()

    decision_res = MRBService.process_review_decision(
        db=db,
        review_id=str(mrb_ticket.id),
        req=MRBReviewDecisionRequest(
            action="APPROVE",
            verified_ok_qty=50,
            verified_reject_qty=0,
            disposition="VERIFIED_OK",
            review_notes="Quality visual check passed 100%."
        ),
        current_user=quality_user
    )
    assert decision_res.success is True
    assert decision_res.item.status == "APPROVED"


    # 6. Verify stage state is now UNLOCKED
    state_after = OMSIntegrationService.get_current_stage_state(db, wo, "F1")
    assert state_after["mrb_lock_status"] == "UNLOCKED"
    assert state_after["mrb_approved_movable_qty"] == 50
    assert state_after["mrb_pending_qty"] == 0

    # 7. Movement now SUCCEEDS!
    move_res = ProductionService.move_parts(
        db,
        MovePartsRequest(
            wo_number=wo.wo_number,
            from_stage="F1",
            to_stage="F2",
            quantity_moved=50
        )
    )
    assert move_res.success is True
    assert move_res.quantity_moved == 50

    # 8. After movement, available approved movable is 0
    state_moved = OMSIntegrationService.get_current_stage_state(db, wo, "F1")
    assert state_moved["on_hand_qty"] == 0
    assert state_moved["mrb_approved_movable_qty"] == 0


def test_mrb_quality_gate_quantity_adjustment(db):
    """If Quality adjusts OK quantity down during MRB, operator can only move the verified quantity."""
    wo = _setup_test_wo(db, qty=100)

    # Operator reports 40 Good, 0 Rej
    ProductionService.record_stage_production(
        db,
        RecordStageProductionRequest(
            wo_number=wo.wo_number,
            stage="F1",
            good_qty=40,
            rejected_quantity=0
        )
    )

    mrb_ticket = db.query(MRBReview).filter(
        MRBReview.work_order_id == wo.id,
        MRBReview.stage == "F1"
    ).first()

    planner_user = User(
        id=uuid.uuid4(),
        email=f"planner-{uuid.uuid4().hex[:6]}@vspl.com",
        full_name="Planner Anjali",
        hashed_password="mockhashedpassword",
        role="PLANNER",
        is_active=True
    )


    db.add(planner_user)
    db.commit()

    # Planner adjusts: 35 OK, 5 Rejected
    decision_res = MRBService.process_review_decision(
        db=db,
        review_id=str(mrb_ticket.id),
        req=MRBReviewDecisionRequest(
            action="ADJUST",
            verified_ok_qty=35,
            verified_reject_qty=5,
            disposition="SCRAP",
            review_notes="5 pieces had shrinkage porosity on flange."
        ),
        current_user=planner_user
    )
    assert decision_res.success is True
    assert decision_res.item.status == "ADJUSTED"


    # Attempting to move 40 pieces must fail
    with pytest.raises(HTTPException) as exc_info:
        ProductionService.move_parts(
            db,
            MovePartsRequest(
                wo_number=wo.wo_number,
                from_stage="F1",
                to_stage="F2",
                quantity_moved=40
            )
        )
    assert exc_info.value.status_code == 400

    # Moving verified 35 pieces succeeds
    move_res = ProductionService.move_parts(
        db,
        MovePartsRequest(
            wo_number=wo.wo_number,
            from_stage="F1",
            to_stage="F2",
            quantity_moved=35
        )
    )
    assert move_res.success is True
    assert move_res.quantity_moved == 35


def test_mrb_batch_stage_approval(db):
    """Quality or Planning can batch-approve all pending tickets for a WO/stage to unlock movement."""
    wo = _setup_test_wo(db, qty=100)

    # 2 production entries at F1 in different shifts
    ProductionService.record_stage_production(
        db, RecordStageProductionRequest(wo_number=wo.wo_number, stage="F1", good_qty=20, rejected_quantity=0)
    )
    ProductionService.record_stage_production(
        db, RecordStageProductionRequest(wo_number=wo.wo_number, stage="F1", good_qty=30, rejected_quantity=0)
    )

    state = OMSIntegrationService.get_current_stage_state(db, wo, "F1")
    assert state["mrb_lock_status"] == "LOCKED"
    assert len(state["pending_mrb_tickets"]) == 2

    quality_user = User(
        id=uuid.uuid4(),
        email=f"qa-{uuid.uuid4().hex[:6]}@vspl.com",
        full_name="Quality Lead",
        hashed_password="mockhashedpassword",
        role="QA",
        is_active=True
    )
    db.add(quality_user)
    db.commit()

    approved_count = MRBService.approve_stage_reviews(
        db=db,
        wo_number=wo.wo_number,
        stage="F1",
        current_user=quality_user,
        notes="Batch shift approval"
    )
    assert approved_count == 2

    # Movement of all 50 pieces is now unlocked
    move_res = ProductionService.move_parts(
        db,
        MovePartsRequest(
            wo_number=wo.wo_number,
            from_stage="F1",
            to_stage="F2",
            quantity_moved=50
        )
    )
    assert move_res.success is True
    assert move_res.quantity_moved == 50


