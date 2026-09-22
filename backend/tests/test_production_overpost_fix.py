"""Regression tests for the production quantity overposting fix:

Root cause: ProductionService.record_stage_production validated a new production
transaction against StageWIP.available_wip (= inproc_qty + onhand_qty), instead of
against inproc_qty alone (the material still physically unprocessed at the stage).
Because available_wip also includes onhand_qty -- material a PRIOR production entry
already completed and is simply awaiting movement -- validating a NEW entry against it
let cumulative OK run past the stage's ent_qty (and therefore past the authoritative
target derived from it) with no ceiling. Fixed by validating against inproc_qty, the
already-existing, already-correct "material remaining to be processed" figure the OMS
Engine already computes -- no new formula invented.

Movement (ProductionService.move_parts) is unchanged: it is a separate transaction
governed by its own, pre-existing available_wip ceiling, exactly as before.
"""
import time
import uuid
import threading
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.core.rate_limit import limiter
from app.main import app
from app.services.seed_service import seed_database_if_empty
from app.services.operations_service import OperationsService
from app.services.production_service import ProductionService
from app.schemas.operations import OrderIntakeCreate
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest
from app.models.work_order import WorkOrder
from app.models.production_movement import StageWIP, ProductionMovement
from app.models.production import ProductionUpdate

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
        customer_code=f"CUST-{uuid.uuid4().hex[:6]}", customer_name="Overpost Test Co",
        customer_po=f"PO-{uuid.uuid4().hex[:8]}", part_number=f"PART-{uuid.uuid4().hex[:6]}",
        po_quantity=po_qty, max_batch_size=po_qty
    ))
    return res.wos_created[0]


def _wip(db, wo_num, stage="F1"):
    wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first()
    return db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == stage).first()


# ---------------------------------------------------------------------------
# 1-3. Basic overpost boundary: 50 + 50 allowed, third rejected
# ---------------------------------------------------------------------------

def test_target_100_first_production_50_allowed(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    resp = ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    assert resp.success is True
    assert _wip(db_session, wo).ok_qty == 50


def test_target_100_second_production_50_allowed(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    resp = ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    assert resp.success is True
    assert _wip(db_session, wo).ok_qty == 100


def test_target_100_third_production_1_rejected(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    with pytest.raises(HTTPException) as exc:
        ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
            wo_number=wo, stage="F1", good_qty=1, rejected_quantity=0
        ))
    assert exc.value.status_code == 400
    assert _wip(db_session, wo).ok_qty == 100, "rejected transaction must not touch cumulative OK"


# ---------------------------------------------------------------------------
# 4-5. existing 80 + new 20 allowed; existing 80 + new 21 rejected
# ---------------------------------------------------------------------------

def test_existing_80_plus_new_20_allowed(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=80, rejected_quantity=0
    ))
    resp = ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=20, rejected_quantity=0
    ))
    assert resp.success is True
    assert _wip(db_session, wo).ok_qty == 100


def test_existing_80_plus_new_21_rejected(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=80, rejected_quantity=0
    ))
    with pytest.raises(HTTPException) as exc:
        ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
            wo_number=wo, stage="F1", good_qty=21, rejected_quantity=0
        ))
    assert exc.value.status_code == 400
    assert _wip(db_session, wo).ok_qty == 80


# ---------------------------------------------------------------------------
# 6. Partial production in arbitrary increments
# ---------------------------------------------------------------------------

def test_partial_production_arbitrary_increments(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    for qty in (25, 25, 25, 25):
        resp = ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
            wo_number=wo, stage="F1", good_qty=qty, rejected_quantity=0
        ))
        assert resp.success is True
    assert _wip(db_session, wo).ok_qty == 100

    with pytest.raises(HTTPException):
        ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
            wo_number=wo, stage="F1", good_qty=1, rejected_quantity=0
        ))


# ---------------------------------------------------------------------------
# 7-9. Partial movement after partial production; multiple production/movement txns
# ---------------------------------------------------------------------------

def test_partial_movement_after_partial_production_full_cycle(db_session):
    """The exact section-13 scenario: produce 50, move 50, produce 50, move 50,
    then a third production entry of 1 must be rejected with no ledger row created
    and no WIP corruption."""
    wo = _fresh_wo(db_session, po_qty=100)

    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    mov1 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=50, rejected_quantity=0
    ))
    assert mov1.success is True

    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    mov2 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=50, rejected_quantity=0
    ))
    assert mov2.success is True

    f1 = _wip(db_session, wo, "F1")
    f2 = _wip(db_session, wo, "F2")
    assert f1.ok_qty == 100
    assert f1.inproc_qty == 0, "no unprocessed material must remain once target is fully produced"
    assert f2.ent_qty == 100

    prod_count_before = db_session.query(ProductionUpdate).filter(ProductionUpdate.work_order_id == db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo).first().id).count()

    with pytest.raises(HTTPException):
        ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
            wo_number=wo, stage="F1", good_qty=1, rejected_quantity=0
        ))

    prod_count_after = db_session.query(ProductionUpdate).filter(ProductionUpdate.work_order_id == db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo).first().id).count()
    assert prod_count_after == prod_count_before, "a rejected overpost must create no ledger row"
    assert _wip(db_session, wo, "F1").ok_qty == 100, "a rejected overpost must not modify cumulative totals"


def test_multiple_production_transactions_accumulate_correctly(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    for qty in (10, 20, 30, 40):
        ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
            wo_number=wo, stage="F1", good_qty=qty, rejected_quantity=0
        ))
    assert _wip(db_session, wo).ok_qty == 100


def test_multiple_movement_transactions_after_multiple_production(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    for qty in (10, 20, 30, 40):
        ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
            wo_number=wo, stage="F1", good_qty=qty, rejected_quantity=0
        ))
    for qty in (25, 25, 25, 25):
        mov = ProductionService.move_parts(db_session, MovePartsRequest(
            wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=qty, rejected_quantity=0
        ))
        assert mov.success is True
    f2 = _wip(db_session, wo, "F2")
    assert f2.ent_qty == 100


# ---------------------------------------------------------------------------
# 10-11. Production/Move input must start blank (frontend contract, spot-checked here
# via the response schema -- the actual blank-input behavior is a frontend concern
# already verified live in the browser; this asserts the backend never implies or
# requires a prefilled value).
# ---------------------------------------------------------------------------

def test_production_response_never_implies_a_prefill_value(db_session):
    """The production entry endpoint must accept an explicit, small delta and never
    require or assume the caller sends the full remaining target -- proving the API
    contract itself is delta-based, not cumulative-based."""
    wo = _fresh_wo(db_session, po_qty=100)
    resp = ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=1, rejected_quantity=0
    ))
    assert resp.good_qty == 1
    assert resp.stage_ok_total == 1


def test_move_response_reports_only_the_requested_delta(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    mov = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number=wo, from_stage="F1", to_stage="F2", quantity_moved=1, rejected_quantity=0
    ))
    assert mov.quantity_moved == 1


# ---------------------------------------------------------------------------
# 12. No WIP created from rejected quantity
# ---------------------------------------------------------------------------

def test_no_wip_created_from_rejected_quantity(db_session):
    wo = _fresh_wo(db_session, po_qty=100)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=0, rejected_quantity=30
    ))
    wip = _wip(db_session, wo)
    assert wip.ok_qty == 0
    assert wip.rejected_qty == 30
    assert wip.available_wip == 70, "rejected quantity must never contribute to movable WIP"


# ---------------------------------------------------------------------------
# 13-14. Overproduction creates no ledger row / does not modify cumulative totals
# ---------------------------------------------------------------------------

def test_overproduction_creates_no_ledger_row_and_no_totals_change(db_session):
    wo = _fresh_wo(db_session, po_qty=50)
    ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
        wo_number=wo, stage="F1", good_qty=50, rejected_quantity=0
    ))
    wo_row = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo).first()
    before_count = db_session.query(ProductionUpdate).filter(ProductionUpdate.work_order_id == wo_row.id).count()
    before_wip = _wip(db_session, wo)
    before_ok, before_ent = before_wip.ok_qty, before_wip.ent_qty

    with pytest.raises(HTTPException) as exc:
        ProductionService.record_stage_production(db_session, RecordStageProductionRequest(
            wo_number=wo, stage="F1", good_qty=5, rejected_quantity=0
        ))
    assert exc.value.status_code == 400

    after_count = db_session.query(ProductionUpdate).filter(ProductionUpdate.work_order_id == wo_row.id).count()
    after_wip = _wip(db_session, wo)
    assert after_count == before_count
    assert after_wip.ok_qty == before_ok
    assert after_wip.ent_qty == before_ent


# ---------------------------------------------------------------------------
# 15. Concurrency -- final committed total never exceeds the authoritative target
# ---------------------------------------------------------------------------

SEEDED_LOGINS = {"ADMIN": ("admin@vspl.com", "admin123")}

_SQLITE_CONCURRENCY_SKIP_REASON = (
    "SQLite serializes writers at the process level (single-writer lock), which "
    "masks real interleaved-transaction races that only manifest under PostgreSQL's "
    "row-level locking. This test requires DATABASE_URL to point at PostgreSQL."
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


def _login(client):
    email, password = SEEDED_LOGINS["ADMIN"]
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.skipif(settings.DATABASE_URL.startswith("sqlite"), reason=_SQLITE_CONCURRENCY_SKIP_REASON)
def test_concurrent_production_cannot_exceed_allowable_target():
    """Target 100, existing OK 60. User A submits 40, User B submits 20 concurrently.
    The final committed cumulative OK must never exceed 100."""
    with TestClient(app) as c:
        token = _login(c)
        resp = c.post(
            "/api/v1/operations/intake",
            headers=_auth(token),
            json={
                "customer_code": "CUST-CONCURRENT", "customer_name": "Concurrent Test Co",
                "customer_po": f"PO-CONC-{uuid.uuid4().hex[:8]}",
                "part_number": f"PART-CONC-{uuid.uuid4().hex[:6]}",
                "po_quantity": 100, "max_batch_size": 100
            }
        )
        wo = resp.json()["wos_created"][0]
        c.post(
            "/api/v1/production/entry", headers=_auth(token),
            json={"wo_number": wo, "stage": "F1", "good_qty": 60, "rejected_quantity": 0}
        )

    results = {}

    def do_entry(key, qty):
        with TestClient(app) as c2:
            r = c2.post(
                "/api/v1/production/entry", headers=_auth(token),
                json={"wo_number": wo, "stage": "F1", "good_qty": qty, "rejected_quantity": 0}
            )
            results[key] = r

    t1 = threading.Thread(target=do_entry, args=("A", 40))
    t2 = threading.Thread(target=do_entry, args=("B", 20))
    t1.start(); t2.start()
    t1.join(); t2.join()

    successful_total = sum(
        r.json()["good_qty"] for r in results.values() if r.status_code == 200
    )
    # Only one of the two (40 or 20) can fit within the remaining 40 -- both fitting
    # simultaneously (60 total) would exceed the target of 100.
    assert 60 + successful_total <= 100, f"overposted: 60 existing + {successful_total} new exceeds target 100"
