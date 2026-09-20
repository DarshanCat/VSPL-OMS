"""
Regression tests for the deep security/debug audit pass.

Each test targets one specific, verified defect found and fixed in this pass:
  1. `MovePartsRequest.operator_id` allowed a client to attribute a production movement
     ledger row to an arbitrary other user's account (FK-level identity spoofing).
  2. `oms_core.storage.save_upload` did not sanitize the client-supplied upload filename,
     allowing path traversal outside the intended per-run upload directory.
  3. `/api/v1/auth/login` had no brute-force/rate-limit protection.
  4. `/api/v1/admin/audit-logs` accepted an unbounded `limit` query parameter.
  5. `/api/v1/oms/run-cycle` returned the raw exception message to the client on failure.
"""
import uuid
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.database import Base
from app.core.rate_limit import limiter
from app.main import app
from app.services.seed_service import seed_database_if_empty
from app.services.production_service import ProductionService
from app.schemas.production import MovePartsRequest
from app.models.work_order import WorkOrder
from app.models.production_movement import ProductionMovement
from app.oms_core.storage import save_upload

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The login rate limiter is process-global (in-memory); reset it around each test so
    one test's login attempts don't spuriously throttle another test's real login."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    seed_database_if_empty(session)
    yield session
    session.close()


def test_operator_id_cannot_be_spoofed_via_request_body(db_session):
    """
    A client must not be able to attribute a movement to an arbitrary other user by
    supplying an operator_id in the request. The field no longer exists on the schema,
    so extra data is simply ignored by Pydantic; the ledger row must always carry the
    real authenticated caller's id (None here, since no current_user is passed by the
    service-layer test harness -- the point is that nothing client-supplied is honored).
    """
    from app.models.user import User

    victim = db_session.query(User).filter(User.email == "admin@vspl.com").first()
    assert victim is not None

    wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == "WO-1001").first()

    # Attempt to smuggle an operator_id impersonating another real user via extra,
    # schema-unrecognized request data.
    payload = {
        "wo_number": "WO-1001",
        "from_stage": "F2",
        "to_stage": "F3",
        "quantity_moved": 10,
        "operator_id": str(victim.id),
    }
    req = MovePartsRequest(**payload)
    assert not hasattr(req, "operator_id")

    mov = ProductionService.move_parts(db_session, req, current_user=None)
    assert mov.success is True

    saved = db_session.query(ProductionMovement).filter(
        ProductionMovement.movement_id == mov.movement_id
    ).first()
    # No current_user was supplied, so operator_id must be None -- never the victim's id
    # that was attempted via the (now nonexistent) request field.
    assert saved.operator_id is None
    assert saved.operator_id != victim.id


def test_upload_path_traversal_is_blocked(tmp_path):
    """A crafted filename must never let a saved upload escape its intended run directory."""
    import asyncio

    class FakeUploadFile:
        def __init__(self, filename, content=b"data"):
            self.filename = filename
            self._content = content

        async def read(self):
            return self._content

    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    outside_target = tmp_path / "escaped.txt"
    assert not outside_target.exists()

    traversal_file = FakeUploadFile("../escaped.txt")
    result = asyncio.run(save_upload(traversal_file, run_dir))

    assert not outside_target.exists()
    # Either rejected outright, or saved safely inside run_dir under its base name.
    if result is not None:
        saved_path = Path(result)
        assert run_dir.resolve() in saved_path.resolve().parents


def test_login_rate_limited_after_repeated_attempts():
    """Repeated login attempts from the same client must eventually be throttled (429)."""
    with TestClient(app) as client:
        statuses = []
        for _ in range(15):
            resp = client.post("/api/v1/auth/login", json={
                "email": "nonexistent-brute-force-test@vspl.com",
                "password": "wrong",
            })
            statuses.append(resp.status_code)
        assert 429 in statuses, f"expected a 429 among repeated login attempts, got {statuses}"


def test_audit_logs_limit_is_bounded():
    """The audit-logs endpoint must reject an absurdly large limit rather than serve it unbounded."""
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": "admin@vspl.com", "password": "admin123"})
        assert login.status_code == 200
        token = login.json()["access_token"]

        resp = client.get(
            "/api/v1/admin/audit-logs",
            params={"limit": 999999999},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


def test_run_cycle_error_does_not_leak_internal_exception_text(monkeypatch):
    """/oms/run-cycle must never echo the raw exception message back to the client."""
    import app.api.v1.oms as oms_module

    def boom(*args, **kwargs):
        raise RuntimeError("SECRET_INTERNAL_DETAIL: /etc/passwd db=postgres://user:pw@host")

    monkeypatch.setattr(oms_module, "run_oms_cycle", boom)

    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"email": "admin@vspl.com", "password": "admin123"})
        token = login.json()["access_token"]

        resp = client.post(
            "/api/v1/oms/run-cycle",
            headers={"Authorization": f"Bearer {token}"},
            data={"allow_partial": "true"},
        )
        assert resp.status_code == 500
        body = resp.text
        assert "SECRET_INTERNAL_DETAIL" not in body
        assert "postgres://" not in body
