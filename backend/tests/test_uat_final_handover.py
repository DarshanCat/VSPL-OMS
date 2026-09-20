"""
Final UAT / production-handover verification tests.

These target the specific defects found and fixed during the final UAT pass and are
not already covered by the existing suite:
  1. Dispatch must credit exactly ONE StageWIP row (the WO's actual terminal stage per
     its persisted route) even when PACKING and BSR are two separate stages in the route
     (previously every stage named PACKING/BSR/DISPATCH was credited, double/triple-counting).
  2. Packing and Dispatch must be idempotent under a repeated client_request_id, matching
     the existing guarantee already covered for Movement/Production entries.
  3. Self-registration must not allow arbitrary-role account creation (privilege escalation).
"""
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.database import Base, get_db
from app.main import app
from app.services.seed_service import seed_database_if_empty
from app.services.production_service import ProductionService
from app.services.packing_service import PackingService
from app.services.dispatch_service import DispatchService
from app.services.operations_service import OperationsService
from app.schemas.production import MovePartsRequest
from app.schemas.packing import PackingUpdateRequest
from app.schemas.dispatch import DispatchRequest
from app.schemas.operations import OrderIntakeCreate, WOReleaseCreate
from app.models.work_order import WorkOrder
from app.models.production_movement import StageWIP
from app.models.packing import PackingRecord, PackingTransaction
from app.models.dispatch import Dispatch
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole

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


def _release_wo_with_split_packing_bsr(db_session, wo_number, qty):
    """Creates a WO whose route has PACKING and BSR as two separate stages (both
    map to the terminal-stage aliasing rules in match_route_stage)."""
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-UAT",
        customer_name="UAT Verification Customer",
        customer_po="PO-UAT-001",
        part_number="BRZ-UAT-01",
        po_quantity=qty,
        max_batch_size=qty,
    ))
    wo_num = res.wos_created[0]
    OperationsService.release_work_order(db_session, WOReleaseCreate(
        wo_number=wo_num,
        physical_wo_qty=qty,
        route_stages=["F1", "F2", "F3", "FI", "PACKING", "BSR", "DISPATCH"],
    ))
    return wo_num


def test_dispatch_credits_only_terminal_stage_with_split_packing_bsr(db_session):
    """
    WO-UAT-001 route: F1 -> F2 -> F3 -> FI -> PACKING -> BSR -> DISPATCH.
    Move 100 through to FI, pack 100, dispatch 100.
    Only the DISPATCH StageWIP row may show ok_qty/moved_out_qty == 100 from the
    dispatch step; PACKING and BSR StageWIP rows must NOT also be credited 100 by
    the dispatch call (they are tracked via PackingRecord / their own transactions).
    """
    qty = 100
    wo_num = _release_wo_with_split_packing_bsr(db_session, "WO-UAT-DISP", qty)
    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()

    for frm, to in [("F1", "F2"), ("F2", "F3"), ("F3", "FI"), ("FI", "PACKING")]:
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo_num, from_stage=frm, to_stage=to, quantity_moved=qty
        ))

    PackingService.update_packing(db_session, PackingUpdateRequest(
        wo_number=wo_num, packed_quantity=qty
    ))

    pre_wips = {w.stage: (w.ok_qty, w.moved_out_qty) for w in db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}

    DispatchService.execute_dispatch(db_session, DispatchRequest(
        wo_number=wo_num, invoice_number="INV-UAT-DISP-001", dispatched_quantity=qty
    ))

    wips = {w.stage: w for w in db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}

    dispatch_wip = wips.get("DISPATCH")
    assert dispatch_wip is not None
    assert dispatch_wip.ok_qty == qty
    assert dispatch_wip.moved_out_qty == qty

    # PACKING and BSR stage rows must be unchanged by the dispatch call itself.
    for stage in ("PACKING", "BSR"):
        if stage in wips and stage in pre_wips:
            before_ok, before_moved = pre_wips[stage]
            assert wips[stage].ok_qty == before_ok, f"{stage} ok_qty was incorrectly credited by dispatch"
            assert wips[stage].moved_out_qty == before_moved, f"{stage} moved_out_qty was incorrectly credited by dispatch"


def test_packing_idempotency_duplicate_client_request_id(db_session):
    """A repeated packing submission with the same client_request_id must not double-pack."""
    qty = 80
    wo_num = _release_wo_with_split_packing_bsr(db_session, "WO-UAT-PACK-IDEMP", qty)
    for frm, to in [("F1", "F2"), ("F2", "F3"), ("F3", "FI"), ("FI", "PACKING")]:
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo_num, from_stage=frm, to_stage=to, quantity_moved=qty
        ))

    token = "PACK-IDEMP-TOKEN-1"
    r1 = PackingService.update_packing(db_session, PackingUpdateRequest(
        wo_number=wo_num, packed_quantity=50, client_request_id=token
    ))
    r2 = PackingService.update_packing(db_session, PackingUpdateRequest(
        wo_number=wo_num, packed_quantity=50, client_request_id=token
    ))

    assert r1.total_packed == 50
    assert r2.total_packed == 50
    assert "Duplicate" in r2.message

    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
    pr = db_session.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
    assert pr.packed_qty == 50

    txns = db_session.query(PackingTransaction).filter(PackingTransaction.client_request_id == token).all()
    assert len(txns) == 1


def test_dispatch_idempotency_duplicate_client_request_id(db_session):
    """A repeated dispatch submission with the same client_request_id must not double-ship."""
    qty = 60
    wo_num = _release_wo_with_split_packing_bsr(db_session, "WO-UAT-DISP-IDEMP", qty)
    for frm, to in [("F1", "F2"), ("F2", "F3"), ("F3", "FI"), ("FI", "PACKING")]:
        ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo_num, from_stage=frm, to_stage=to, quantity_moved=qty
        ))
    PackingService.update_packing(db_session, PackingUpdateRequest(wo_number=wo_num, packed_quantity=qty))

    token = "DISP-IDEMP-TOKEN-1"
    d1 = DispatchService.execute_dispatch(db_session, DispatchRequest(
        wo_number=wo_num, invoice_number="INV-UAT-IDEMP-001", dispatched_quantity=qty, client_request_id=token
    ))
    d2 = DispatchService.execute_dispatch(db_session, DispatchRequest(
        wo_number=wo_num, invoice_number="INV-UAT-IDEMP-001", dispatched_quantity=qty, client_request_id=token
    ))

    assert d1.success is True
    assert d2.success is True
    assert "Duplicate" in d2.message

    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
    dispatches = db_session.query(Dispatch).filter(Dispatch.client_request_id == token).all()
    assert len(dispatches) == 1

    pr = db_session.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
    assert pr.dispatched_qty == qty  # not double-counted to 2x qty


def test_registration_requires_admin_role():
    """
    /auth/register must not allow anonymous/self-service account creation with an
    arbitrary role (previously any caller could mint an ADMIN account).
    """
    client = TestClient(app)
    resp = client.post("/api/v1/auth/register", json={
        "full_name": "Attacker",
        "email": "attacker@example.com",
        "password": "password123",
        "role": "admin",
    })
    assert resp.status_code in (401, 403)


def test_seed_does_not_reset_existing_user_credentials(db_session):
    """
    seed_database_if_empty() runs on every application startup. It must never overwrite
    an existing seeded account's password/role — otherwise a real admin's rotated
    password would be silently reset back to the hardcoded demo default on every
    restart/deploy.
    """
    admin = db_session.query(User).filter(User.email == "admin@vspl.com").first()
    assert admin is not None

    admin.hashed_password = hash_password("a-real-rotated-production-password")
    admin.role = UserRole.PRODUCTION_MANAGER  # simulate a real role change too
    db_session.commit()

    # Simulate an application restart re-running the seeder against the same DB.
    seed_database_if_empty(db_session)

    db_session.refresh(admin)
    assert verify_password("a-real-rotated-production-password", admin.hashed_password)
    assert admin.role == UserRole.PRODUCTION_MANAGER


def test_useout_customerout_partout_serialize_uuid_id():
    """
    UserOut/CustomerOut/PartOut declare `id: str`, but their endpoints return raw ORM
    objects whose `id` is a uuid.UUID (via the custom GUID column type). Pydantic v2
    does not auto-coerce UUID -> str for a plain `str` field, which previously crashed
    /auth/register, /admin/customers and /admin/parts with a 500 ResponseValidationError
    on every call. Confirms the fix (a `field_validator` coercing id to str) holds.
    """
    from app.schemas.auth import UserOut
    from app.api.v1.admin import CustomerOut, PartOut

    raw_id = uuid.uuid4()

    user_out = UserOut.model_validate({"id": raw_id, "full_name": "X", "email": "x@x.com", "role": "admin"})
    assert user_out.id == str(raw_id)

    cust_out = CustomerOut.model_validate({"id": raw_id, "customer_code": "C1", "name": "N"})
    assert cust_out.id == str(raw_id)

    part_out = PartOut.model_validate({"id": raw_id, "part_number": "P1", "grade": "G", "description": "D"})
    assert part_out.id == str(raw_id)
