"""
Engineering/Manufacturing Release chain + Rejection Replacement WO regression suite.

Covers:
  - Engineering Release authorization + sequencing
  - Manufacturing Release authorization + requires Engineering Release first
  - Production blocked before Engineering Release, still blocked after only
    Engineering Release, still blocked after Engineering+Manufacturing (before WO
    Release) -- for a WO that has entered the new release-gated flow
  - Production on an ordinary WO that never enters the chain is unaffected
    (backward-compatible activation)
  - WO Release (existing) requires Manufacturing Release once a WO has entered
    the chain
  - Replacement WO creation against the same OAR, audit/disposition linkage, that
    the original WO's target/history is never modified, that it starts unreleased,
    and that it must go through the FULL release chain before production
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.core.security import hash_password, create_access_token
from app.models.user import User, UserRole
from app.models.order import Order, Part, Customer, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.models.nc import NCRecord
from app.services.seed_service import _seed_default_rejection_types

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    _seed_default_rejection_types(db)
    db.commit()
    yield db
    db.close()


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        yield test_db
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(db, email, role):
    user = User(full_name=email.split("@")[0], email=email, hashed_password=hash_password("x"), role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}, user


def _make_wo(db, wo_number, oar_number, qty, stages="F1 -> F2 -> DISPATCH"):
    customer = Customer(customer_code=f"C-{wo_number}", name="Test Customer")
    part = Part(part_number=f"P-{wo_number}", description="Test Part")
    db.add_all([customer, part])
    db.flush()
    order = Order(oar_number=oar_number, customer_id=customer.id, part_id=part.id, customer_po="PO-1",
                  po_qty=qty, max_batch_size=qty, status=OrderStatus.ACCEPT)
    db.add(order)
    db.flush()
    wo = WorkOrder(wo_number=wo_number, order_id=order.id, physical_wo_qty=qty,
                    current_stage="F1", projected_final_good=qty, status=WOStatus.IN_PRODUCTION)
    db.add(wo)
    db.flush()
    stage_list = [s.strip() for s in stages.split("->")]
    for seq, stg in enumerate(stage_list, start=1):
        db.add(WORoute(work_order_id=wo.id, stage=stg, sequence=seq, stage_target_qty=qty,
                        stage_status="In-Progress" if seq == 1 else "Pending"))
    db.add(StageWIP(work_order_id=wo.id, stage=stage_list[0], ent_qty=qty, ok_qty=0, inproc_qty=qty,
                     onhand_qty=0, rejected_qty=0, available_wip=qty))
    db.commit()
    db.refresh(wo)
    return wo


# ---------------------------------------------------------------------------
# Engineering / Manufacturing Release
# ---------------------------------------------------------------------------

def test_engineering_release_requires_engineering_or_admin_role(client, test_db):
    _make_wo(test_db, "WO-REL-1", "OAR-REL-1", 100)
    prod_headers, _ = _auth(test_db, "pm.rel1@vspl.com", UserRole.PRODUCTION_MANAGER)
    resp = client.post("/api/v1/operations/wo/WO-REL-1/engineering-release", headers=prod_headers)
    assert resp.status_code == 403

    eng_headers, _ = _auth(test_db, "eng.rel1@vspl.com", UserRole.ENGINEERING)
    resp = client.post("/api/v1/operations/wo/WO-REL-1/engineering-release", headers=eng_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["engineering_released_by"] == "eng.rel1"


def test_manufacturing_release_requires_engineering_release_first(client, test_db):
    _make_wo(test_db, "WO-REL-2", "OAR-REL-2", 100)
    mfg_headers, _ = _auth(test_db, "mfg.rel2@vspl.com", UserRole.MANUFACTURING)

    resp = client.post("/api/v1/operations/wo/WO-REL-2/manufacturing-release", headers=mfg_headers)
    assert resp.status_code == 400
    assert "Engineering Release" in resp.json()["detail"]

    eng_headers, _ = _auth(test_db, "eng.rel2@vspl.com", UserRole.ENGINEERING)
    assert client.post("/api/v1/operations/wo/WO-REL-2/engineering-release", headers=eng_headers).status_code == 200

    resp = client.post("/api/v1/operations/wo/WO-REL-2/manufacturing-release", headers=mfg_headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_manufacturing_release_requires_manufacturing_or_admin_role(client, test_db):
    _make_wo(test_db, "WO-REL-3", "OAR-REL-3", 100)
    eng_headers, _ = _auth(test_db, "eng.rel3@vspl.com", UserRole.ENGINEERING)
    client.post("/api/v1/operations/wo/WO-REL-3/engineering-release", headers=eng_headers)

    wrong_headers, _ = _auth(test_db, "qa.rel3@vspl.com", UserRole.QA)
    resp = client.post("/api/v1/operations/wo/WO-REL-3/manufacturing-release", headers=wrong_headers)
    assert resp.status_code == 403


def test_production_blocked_before_manufacturing_release(client, test_db):
    """Backward-compatible activation: once Engineering Release is recorded on a WO,
    production is blocked until Manufacturing Release completes."""
    _make_wo(test_db, "WO-REL-4", "OAR-REL-4", 100)
    eng_headers, _ = _auth(test_db, "eng.rel4@vspl.com", UserRole.ENGINEERING)
    op_headers, _ = _auth(test_db, "op.rel4@vspl.com", UserRole.MACHINE_OPERATOR)

    client.post("/api/v1/operations/wo/WO-REL-4/engineering-release", headers=eng_headers)

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-REL-4", "stage": "F1", "good_qty": 10, "rejected_quantity": 0
    }, headers=op_headers)
    assert resp.status_code == 400
    assert "Manufacturing Release" in resp.json()["detail"]


def test_production_unaffected_when_release_chain_never_used(client, test_db):
    """A WO that never enters the new release-gated flow behaves exactly as before --
    zero regression for the existing intake-and-produce path."""
    _make_wo(test_db, "WO-REL-5", "OAR-REL-5", 100)
    op_headers, _ = _auth(test_db, "op.rel5@vspl.com", UserRole.MACHINE_OPERATOR)

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-REL-5", "stage": "F1", "good_qty": 10, "rejected_quantity": 0
    }, headers=op_headers)
    assert resp.status_code == 200


def test_wo_release_requires_manufacturing_release_once_chain_started(client, test_db):
    _make_wo(test_db, "WO-REL-6", "OAR-REL-6", 100)
    eng_headers, _ = _auth(test_db, "eng.rel6@vspl.com", UserRole.ENGINEERING)
    planner_headers, _ = _auth(test_db, "planner.rel6@vspl.com", UserRole.PLANNER)

    client.post("/api/v1/operations/wo/WO-REL-6/engineering-release", headers=eng_headers)

    resp = client.post("/api/v1/operations/wo-release", json={
        "wo_number": "WO-REL-6", "physical_wo_qty": 100, "route_stages": ["F1", "F2", "DISPATCH"]
    }, headers=planner_headers)
    assert resp.status_code == 400
    assert "Manufacturing Release" in resp.json()["detail"]


def test_normal_wo_complete_release_chain_succeeds(client, test_db):
    _make_wo(test_db, "WO-REL-7", "OAR-REL-7", 100)
    eng_headers, _ = _auth(test_db, "eng.rel7@vspl.com", UserRole.ENGINEERING)
    mfg_headers, _ = _auth(test_db, "mfg.rel7@vspl.com", UserRole.MANUFACTURING)
    planner_headers, _ = _auth(test_db, "planner.rel7@vspl.com", UserRole.PLANNER)
    op_headers, _ = _auth(test_db, "op.rel7@vspl.com", UserRole.MACHINE_OPERATOR)

    assert client.post("/api/v1/operations/wo/WO-REL-7/engineering-release", headers=eng_headers).status_code == 200
    assert client.post("/api/v1/operations/wo/WO-REL-7/manufacturing-release", headers=mfg_headers).status_code == 200
    resp = client.post("/api/v1/operations/wo-release", json={
        "wo_number": "WO-REL-7", "physical_wo_qty": 100, "route_stages": ["F1", "F2", "DISPATCH"]
    }, headers=planner_headers)
    assert resp.status_code == 200, resp.text

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-REL-7", "stage": "F1", "good_qty": 10, "rejected_quantity": 0
    }, headers=op_headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Rejection Replacement WO
# ---------------------------------------------------------------------------

def _seed_nc(db, wo, qty=10, defect="DEF-POROSITY"):
    from app.models.nc import next_nc_number
    nc = NCRecord(nc_number=next_nc_number(db), work_order_id=wo.id, stage="F1",
                  defect_code=defect, qty=qty, status="Open")
    db.add(nc)
    db.commit()
    db.refresh(nc)
    return nc


def test_replacement_wo_created_against_same_oar(client, test_db):
    wo = _make_wo(test_db, "WO-REPL-1", "OAR-REPL-1", 100)
    nc = _seed_nc(test_db, wo, qty=10)
    qa_headers, _ = _auth(test_db, "qa.repl1@vspl.com", UserRole.QA)

    resp = client.post("/api/v1/rejection/replacement", json={
        "nc_number": nc.nc_number, "quantity": 10, "reason": "2 pcs rejected, replacement required"
    }, headers=qa_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["oar_number"] == "OAR-REPL-1"
    assert body["original_wo_number"] == "WO-REPL-1"
    replacement_wo_number = body["replacement_wo_number"]
    assert replacement_wo_number != "WO-REPL-1"

    replacement = test_db.query(WorkOrder).filter(WorkOrder.wo_number == replacement_wo_number).first()
    assert replacement is not None
    assert replacement.is_replacement is True
    assert str(replacement.source_wo_id) == str(wo.id)
    assert replacement.order_id == wo.order_id
    assert replacement.physical_wo_qty == 10

    # Original WO's own target/history must never be modified.
    test_db.refresh(wo)
    assert wo.physical_wo_qty == 100
    assert wo.is_replacement is False


def test_replacement_wo_requires_quality_or_admin_role(client, test_db):
    wo = _make_wo(test_db, "WO-REPL-2", "OAR-REPL-2", 100)
    nc = _seed_nc(test_db, wo, qty=5)
    prod_headers, _ = _auth(test_db, "pm.repl2@vspl.com", UserRole.PRODUCTION_MANAGER)
    resp = client.post("/api/v1/rejection/replacement", json={
        "nc_number": nc.nc_number, "quantity": 5, "reason": "test"
    }, headers=prod_headers)
    assert resp.status_code == 403


def test_replacement_wo_disposition_linkage(client, test_db):
    from app.models.rejection_disposition import RejectionDisposition
    wo = _make_wo(test_db, "WO-REPL-3", "OAR-REPL-3", 100)
    nc = _seed_nc(test_db, wo, qty=8)
    qa_headers, _ = _auth(test_db, "qa.repl3@vspl.com", UserRole.QA)

    resp = client.post("/api/v1/rejection/replacement", json={
        "nc_number": nc.nc_number, "quantity": 8, "reason": "Porosity rejection replacement"
    }, headers=qa_headers)
    assert resp.status_code == 200
    replacement_wo_number = resp.json()["replacement_wo_number"]

    disp = test_db.query(RejectionDisposition).filter(
        RejectionDisposition.action == "REPLACEMENT", RejectionDisposition.nc_record_id == nc.id
    ).first()
    assert disp is not None
    assert disp.destination_wo_number == replacement_wo_number
    assert disp.quantity == 8

    test_db.refresh(nc)
    assert nc.status == "Closed"


def test_replacement_wo_not_auto_generated_from_rejection_entry(client, test_db):
    """Recording a rejection alone must never create a replacement WO -- only the
    explicit replacement endpoint does."""
    _make_wo(test_db, "WO-REPL-4", "OAR-REPL-4", 100)
    op_headers, _ = _auth(test_db, "op.repl4@vspl.com", UserRole.MACHINE_OPERATOR)

    before_count = test_db.query(WorkOrder).count()
    resp = client.post("/api/v1/production/entry", json={
        "wo_number": "WO-REPL-4", "stage": "F1", "good_qty": 8, "rejected_quantity": 2,
        "defect_code": "DEF-POROSITY"
    }, headers=op_headers)
    assert resp.status_code == 200
    after_count = test_db.query(WorkOrder).count()
    assert after_count == before_count


def test_replacement_wo_starts_unreleased(client, test_db):
    wo = _make_wo(test_db, "WO-RGATE-1", "OAR-RGATE-1", 100)
    nc = _seed_nc(test_db, wo, qty=10)
    qa_headers, _ = _auth(test_db, "qa.rgate1@vspl.com", UserRole.QA)

    resp = client.post("/api/v1/rejection/replacement", json={
        "nc_number": nc.nc_number, "quantity": 10, "reason": "test"
    }, headers=qa_headers)
    replacement_wo_number = resp.json()["replacement_wo_number"]
    replacement = test_db.query(WorkOrder).filter(WorkOrder.wo_number == replacement_wo_number).first()
    assert replacement.engineering_released_at is None
    assert replacement.manufacturing_released_at is None
    assert replacement.release_date is None
    assert replacement.is_replacement is True


def _create_replacement(client, qa_headers, nc_number, qty=10, reason="Replacement required"):
    resp = client.post("/api/v1/rejection/replacement", json={
        "nc_number": nc_number, "quantity": qty, "reason": reason
    }, headers=qa_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["replacement_wo_number"]


def test_replacement_wo_production_blocked_before_engineering_release(client, test_db):
    wo = _make_wo(test_db, "WO-RGATE-2", "OAR-RGATE-2", 100)
    nc = _seed_nc(test_db, wo, qty=10)
    qa_headers, _ = _auth(test_db, "qa.rgate2@vspl.com", UserRole.QA)
    op_headers, _ = _auth(test_db, "op.rgate2@vspl.com", UserRole.MACHINE_OPERATOR)

    replacement_wo_number = _create_replacement(client, qa_headers, nc.nc_number)

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": replacement_wo_number, "stage": "F1", "good_qty": 5, "rejected_quantity": 0
    }, headers=op_headers)
    assert resp.status_code == 400
    assert "Engineering Release" in resp.json()["detail"]


def test_replacement_wo_production_blocked_before_manufacturing_release(client, test_db):
    wo = _make_wo(test_db, "WO-RGATE-3", "OAR-RGATE-3", 100)
    nc = _seed_nc(test_db, wo, qty=10)
    qa_headers, _ = _auth(test_db, "qa.rgate3@vspl.com", UserRole.QA)
    eng_headers, _ = _auth(test_db, "eng.rgate3@vspl.com", UserRole.ENGINEERING)
    op_headers, _ = _auth(test_db, "op.rgate3@vspl.com", UserRole.MACHINE_OPERATOR)

    replacement_wo_number = _create_replacement(client, qa_headers, nc.nc_number)

    resp = client.post(f"/api/v1/operations/wo/{replacement_wo_number}/engineering-release", headers=eng_headers)
    assert resp.status_code == 200

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": replacement_wo_number, "stage": "F1", "good_qty": 5, "rejected_quantity": 0
    }, headers=op_headers)
    assert resp.status_code == 400
    assert "Manufacturing Release" in resp.json()["detail"]


def test_replacement_wo_production_blocked_before_wo_release(client, test_db):
    wo = _make_wo(test_db, "WO-RGATE-4", "OAR-RGATE-4", 100)
    nc = _seed_nc(test_db, wo, qty=10)
    qa_headers, _ = _auth(test_db, "qa.rgate4@vspl.com", UserRole.QA)
    eng_headers, _ = _auth(test_db, "eng.rgate4@vspl.com", UserRole.ENGINEERING)
    mfg_headers, _ = _auth(test_db, "mfg.rgate4@vspl.com", UserRole.MANUFACTURING)
    op_headers, _ = _auth(test_db, "op.rgate4@vspl.com", UserRole.MACHINE_OPERATOR)

    replacement_wo_number = _create_replacement(client, qa_headers, nc.nc_number)
    client.post(f"/api/v1/operations/wo/{replacement_wo_number}/engineering-release", headers=eng_headers)
    resp = client.post(f"/api/v1/operations/wo/{replacement_wo_number}/manufacturing-release", headers=mfg_headers)
    assert resp.status_code == 200

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": replacement_wo_number, "stage": "F1", "good_qty": 5, "rejected_quantity": 0
    }, headers=op_headers)
    assert resp.status_code == 400
    assert "WO Release" in resp.json()["detail"]

    # The existing WO Release endpoint itself must also refuse a replacement WO
    # until Manufacturing Release -- verify the symmetric case with a fresh one.
    nc2 = _seed_nc(test_db, wo, qty=5)
    other_replacement = _create_replacement(client, qa_headers, nc2.nc_number, qty=5, reason="second")
    planner_headers, _ = _auth(test_db, "planner.rgate4@vspl.com", UserRole.PLANNER)
    resp = client.post("/api/v1/operations/wo-release", json={
        "wo_number": other_replacement, "physical_wo_qty": 5, "route_stages": ["F1", "F2", "DISPATCH"]
    }, headers=planner_headers)
    assert resp.status_code == 400
    assert "Engineering Release" in resp.json()["detail"]


def test_replacement_wo_production_succeeds_after_full_release_chain(client, test_db):
    wo = _make_wo(test_db, "WO-RGATE-5", "OAR-RGATE-5", 100)
    nc = _seed_nc(test_db, wo, qty=10)
    qa_headers, _ = _auth(test_db, "qa.rgate5@vspl.com", UserRole.QA)
    eng_headers, _ = _auth(test_db, "eng.rgate5@vspl.com", UserRole.ENGINEERING)
    mfg_headers, _ = _auth(test_db, "mfg.rgate5@vspl.com", UserRole.MANUFACTURING)
    planner_headers, _ = _auth(test_db, "planner.rgate5@vspl.com", UserRole.PLANNER)
    op_headers, _ = _auth(test_db, "op.rgate5@vspl.com", UserRole.MACHINE_OPERATOR)

    replacement_wo_number = _create_replacement(client, qa_headers, nc.nc_number, qty=10)

    assert client.post(f"/api/v1/operations/wo/{replacement_wo_number}/engineering-release", headers=eng_headers).status_code == 200
    assert client.post(f"/api/v1/operations/wo/{replacement_wo_number}/manufacturing-release", headers=mfg_headers).status_code == 200
    resp = client.post("/api/v1/operations/wo-release", json={
        "wo_number": replacement_wo_number, "physical_wo_qty": 10, "route_stages": ["F1", "F2", "DISPATCH"]
    }, headers=planner_headers)
    assert resp.status_code == 200, resp.text

    resp = client.post("/api/v1/production/entry", json={
        "wo_number": replacement_wo_number, "stage": "F1", "good_qty": 5, "rejected_quantity": 0
    }, headers=op_headers)
    assert resp.status_code == 200
