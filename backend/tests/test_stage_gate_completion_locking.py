import uuid
import pytest
from fastapi import HTTPException
from app.core.database import SessionLocal, auto_migrate_schema
from app.models.user import User, UserRole
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.services.production_service import ProductionService
from app.services.oms_integration_service import OMSIntegrationService
from app.services.mrb_service import MRBService
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest


@pytest.fixture
def db_session():
    auto_migrate_schema()
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


def _setup_released_wo(db, po_qty=391):
    uid = uuid.uuid4().hex[:6]
    cust = db.query(Customer).first()
    if not cust:
        cust = Customer(customer_code=f"C-{uid}", company_name="Test Customer")
        db.add(cust)
        db.flush()

    part = db.query(Part).first()
    if not part:
        part = Part(part_number=f"P-{uid}", part_name="Bronze Bushing")
        db.add(part)
        db.flush()

    user = db.query(User).filter(User.email == "qa@vspl.com").first()
    if not user:
        user = User(
            email=f"qa-{uid}@vspl.com",
            full_name="Quality Auditor",
            role=UserRole.QA,
            is_active=True,
            hashed_password="dummy_hash_for_testing"
        )
        db.add(user)
        db.flush()

    order = Order(
        oar_number=f"OAR-{uid}",
        customer_id=cust.id,
        part_id=part.id,
        customer_po=f"PO-{uid}",
        po_qty=po_qty,
        status=OrderStatus.ACCEPT
    )
    db.add(order)
    db.flush()

    wo_num = f"WO-TEST-{uid}"
    wo = WorkOrder(
        wo_number=wo_num,
        order_id=order.id,
        physical_wo_qty=po_qty,
        current_stage="F1",
        status=WOStatus.IN_PRODUCTION
    )
    db.add(wo)
    db.flush()

    # Route: F1 -> F2 -> DISPATCH
    routes = ["F1", "F2", "DISPATCH"]
    for seq, stg in enumerate(routes, start=1):
        r = WORoute(
            work_order_id=wo.id,
            stage=stg,
            sequence=seq,
            stage_target_qty=po_qty,  # Target matches physical_wo_qty (391)
            cumulative_ent_qty=po_qty if seq == 1 else 0,
            cumulative_inproc_qty=po_qty if seq == 1 else 0,
            stage_status="In-Progress" if seq == 1 else "Pending"
        )
        db.add(r)

    f1_wip = StageWIP(
        work_order_id=wo.id,
        stage="F1",
        ent_qty=po_qty,
        ok_qty=0,
        inproc_qty=po_qty,
        onhand_qty=0,
        rejected_qty=0,
        available_wip=po_qty
    )
    db.add(f1_wip)
    db.commit()
    return wo_num, user


def test_released_wo_target_matches_released_quantity(db_session):
    """Target must show 391, NOT an inflated 487."""
    wo_num, user = _setup_released_wo(db_session, po_qty=391)
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
    state = OMSIntegrationService.get_current_stage_state(db_session, wo, "F1")

    assert state["target_qty"] == 391, f"Expected 391, got {state['target_qty']}"
    assert state["remaining_to_produce"] == 391
    assert state["total_produced"] == 0
    assert state["is_gate_locked"] is False


def test_gate_locks_when_full_quantity_produced_and_moved(db_session):
    """When 391 pcs are produced (385 OK + 6 Rej) and 385 moved to F2, F1 must lock completely."""
    wo_num, user = _setup_released_wo(db_session, po_qty=391)
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    # 1. Produce 385 OK + 6 Rej = 391 pcs at F1
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo_num, stage="F1", good_qty=385, rejected_quantity=6, defect_code="DEF-POROSITY"
    ), current_user=user)

    state_after_prod = OMSIntegrationService.get_current_stage_state(db_session, wo, "F1")
    assert state_after_prod["total_produced"] == 391
    assert state_after_prod["ok_completed_qty"] == 385
    assert state_after_prod["rejected_qty"] == 6
    assert state_after_prod["remaining_to_produce"] == 0
    assert state_after_prod["on_hand_qty"] == 385
    assert state_after_prod["is_gate_locked"] is False  # not yet locked because 385 pcs still on-hand

    # 2. Approve MRB review
    MRBService.approve_stage_reviews(db_session, wo_number=wo_num, stage="F1", current_user=user)

    # 3. Move the 385 OK pieces to F2
    ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo_num, from_stage="F1", to_stage="F2", quantity_moved=385, rejected_quantity=0
    ), current_user=user)

    # 4. Check F1 state: 0 product remains, so F1 must lock!
    state_after_move = OMSIntegrationService.get_current_stage_state(db_session, wo, "F1")
    assert state_after_move["on_hand_qty"] == 0
    assert state_after_move["remaining_to_produce"] == 0
    assert state_after_move["is_gate_locked"] is True
    assert state_after_move["stage_status"] == "Completed"

    # 5. Check F2 state: 385 pieces entered and are in-process
    state_f2 = OMSIntegrationService.get_current_stage_state(db_session, wo, "F2")
    assert state_f2["in_process_qty"] == 385
    assert state_f2["is_gate_locked"] is False

    # 6. Current stage of WO advanced to F2
    db_session.refresh(wo)
    assert wo.current_stage == "F2"

    # 7. Attempting to record further production at F1 must be rejected (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
            wo_number=wo_num, stage="F1", good_qty=1, rejected_quantity=0
        ), current_user=user)
    assert exc_info.value.status_code == 400
    assert "Gate 'F1' has completed and passed" in str(exc_info.value.detail)
