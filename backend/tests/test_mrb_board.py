import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from app.core.database import Base
from app.services.seed_service import seed_database_if_empty
from app.services.production_service import ProductionService
from app.services.operations_service import OperationsService
from app.services.mrb_service import MRBService
from app.schemas.production import RecordStageProductionRequest
from app.schemas.operations import OrderIntakeCreate, WorkOrderCreatePayload
from app.schemas.mrb import MRBReviewDecisionRequest
from app.models.work_order import WorkOrder
from app.models.production_movement import StageWIP
from app.models.production import ProductionUpdate
from app.models.mrb import MRBReview
from app.models.user import User, UserRole
from app.core.roles import MRB_ROLES

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


def test_mrb_ticket_auto_generation_and_approval(db_session):
    # 1. Setup Order & Work Order
    intake_res = OperationsService.create_order_intake(
        db_session,
        OrderIntakeCreate(
            customer_code="CUST-VALVE",
            customer_name="Flowserve Controls Ltd",
            customer_po="PO-MRB-001",
            part_number="BRZ-BUSH-100",
            po_quantity=100
        )
    )
    wo_res = OperationsService.create_work_order(
        db_session,
        WorkOrderCreatePayload(
            oar_number=intake_res.oar_number,
            physical_wo_qty=50
        )
    )
    wo_num = wo_res.wo_number
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    # 2. Floor Operator records production at F1: 40 OK, 5 Rejected
    prod_res = ProductionService.record_stage_production(
        db_session,
        RecordStageProductionRequest(
            wo_number=wo_num,
            stage="F1",
            good_qty=40,
            rejected_quantity=5,
            defect_code="DEF-POROSITY",
            operator_name="Ramesh Floor",
            shift="Shift A",
            remarks="Rough casting test run"
        )
    )
    assert prod_res.success is True

    # 3. Verify MRB ticket was automatically created in PENDING status
    mrb_tickets = db_session.query(MRBReview).filter(MRBReview.work_order_id == wo.id).all()
    assert len(mrb_tickets) == 1
    mrb = mrb_tickets[0]
    assert mrb.status == "PENDING"
    assert mrb.reported_ok_qty == 40
    assert mrb.reported_reject_qty == 5
    assert mrb.reported_defect_code == "DEF-POROSITY"
    assert mrb.operator_name == "Ramesh Floor"
    assert mrb.stage == "F1"

    # 4. List reviews via MRBService
    list_res = MRBService.list_reviews(db_session, status_filter="PENDING")
    assert list_res.total_count >= 1
    assert list_res.pending_count >= 1
    item = next(it for it in list_res.items if it.mrb_number == mrb.mrb_number)
    assert item.wo_number == wo_num
    assert item.part_number == "BRZ-BUSH-100"
    assert item.customer_name in ("Flowserve Sanmar Ltd", "Flowserve Controls Ltd")

    # 5. Quality Manager approves the floor entry
    qa_user = User(
        full_name="Priya Quality Lead",
        email="priya.qa@vspl.com",
        role=UserRole.QA,
        hashed_password="x"
    )
    db_session.add(qa_user)
    db_session.flush()

    decision_res = MRBService.process_review_decision(
        db_session,
        review_id=mrb.mrb_number,
        req=MRBReviewDecisionRequest(
            action="APPROVE",
            disposition="SCRAP",
            review_notes="Inspected scrap bin; porosity verified on 5 pcs."
        ),
        current_user=qa_user
    )
    assert decision_res.success is True
    assert decision_res.item.status == "APPROVED"
    assert decision_res.item.reviewed_by_name == "Priya Quality Lead"
    assert decision_res.item.disposition == "SCRAP"

    db_session.refresh(mrb)
    assert mrb.status == "APPROVED"


def test_mrb_quantity_adjustment_reconciles_wip(db_session):
    # 1. Setup Order & Work Order
    intake_res = OperationsService.create_order_intake(
        db_session,
        OrderIntakeCreate(
            customer_code="CUST-VALVE",
            customer_name="Flowserve Controls Ltd",
            customer_po="PO-MRB-002",
            part_number="BRZ-BUSH-100",
            po_quantity=100
        )
    )
    wo_res = OperationsService.create_work_order(
        db_session,
        WorkOrderCreatePayload(
            oar_number=intake_res.oar_number,
            physical_wo_qty=50
        )
    )
    wo_num = wo_res.wo_number
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    # 2. Floor Operator records production: 20 OK, 10 Rejection
    ProductionService.record_stage_production(
        db_session,
        RecordStageProductionRequest(
            wo_number=wo_num,
            stage="F1",
            good_qty=20,
            rejected_quantity=10,
            defect_code="DEF-BLOWHOLE",
            operator_name="Operator Suresh"
        )
    )

    wip_before = db_session.query(StageWIP).filter(
        StageWIP.work_order_id == wo.id,
        StageWIP.stage == "F1"
    ).first()
    assert wip_before.ok_qty == 20
    assert wip_before.rejected_qty == 10

    mrb = db_session.query(MRBReview).filter(MRBReview.work_order_id == wo.id).first()
    assert mrb.status == "PENDING"

    # 3. Quality / Planner clarifies and adjusts:
    # After physical MRB review, 2 of the rejected pieces were actually good (surface grease, not blowholes).
    # Corrected numbers: 22 OK, 8 Rejection
    planner_user = User(
        full_name="Anand Head Planner",
        email="anand.planner@vspl.com",
        role=UserRole.PLANNER,
        hashed_password="x"
    )
    db_session.add(planner_user)
    db_session.flush()

    adj_res = MRBService.process_review_decision(
        db_session,
        review_id=mrb.mrb_number,
        req=MRBReviewDecisionRequest(
            action="ADJUST",
            verified_ok_qty=22,
            verified_reject_qty=8,
            verified_defect_code="DEF-BLOWHOLE",
            disposition="SCRAP",
            review_notes="2 pcs cleaned and re-inspected OK; blowholes confirmed on 8 pcs."
        ),
        current_user=planner_user
    )
    assert adj_res.success is True
    assert adj_res.item.status == "ADJUSTED"
    assert adj_res.item.verified_ok_qty == 22
    assert adj_res.item.verified_reject_qty == 8

    # 4. Verify StageWIP and ProductionUpdate were accurately reconciled
    db_session.refresh(wip_before)
    assert wip_before.ok_qty == 22
    assert wip_before.rejected_qty == 8

    pu = db_session.query(ProductionUpdate).filter(ProductionUpdate.id == mrb.production_update_id).first()
    assert pu.good_qty == 22
    assert pu.reject_qty == 8


def test_mrb_rbac_roles():
    # MRB roles must include ADMIN, QA, PLANNER, CEO
    assert UserRole.ADMIN in MRB_ROLES
    assert UserRole.QA in MRB_ROLES
    assert UserRole.PLANNER in MRB_ROLES
    assert UserRole.CEO in MRB_ROLES
    # Machine Operator / Store cannot approve MRB reviews
    assert UserRole.MACHINE_OPERATOR not in MRB_ROLES
    assert UserRole.STORE not in MRB_ROLES
