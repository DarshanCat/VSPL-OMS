"""Regression tests for the temporary, production-only schema migration endpoint
(app/api/v1/migration.py). This endpoint exists to add users.must_change_password to
a production database whose normal FastAPI startup migration path never reached it --
see the commit history / PRODUCTION_DEPLOYMENT.md for the full incident. It is
deliberately NOT gated by the normal JWT/get_current_user auth path, because that
path itself queries the column being added -- these tests confirm that circularity
is actually avoided, not just assumed.
"""
import os
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.config import settings
from app.core.database import engine
from app.main import app

# This endpoint's SQL (ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...) is Postgres
# syntax -- it is only ever meant to run against production Postgres/Neon, never
# SQLite. Local dev falls back to SQLite only when Docker Postgres isn't reachable
# (see app/core/database.py) -- check the ACTUAL engine dialect, not the configured
# DATABASE_URL, since a Postgres URL that fails to connect silently falls back to a
# SQLite engine in development. Skip the SQL-executing tests in that case, matching
# the existing @pytest.mark.skipif convention used elsewhere for Postgres-only
# concurrency behavior.
_POSTGRES_ONLY_SKIP = "requires a real PostgreSQL connection (Docker not running locally)"
_requires_postgres = pytest.mark.skipif(engine.dialect.name == "sqlite", reason=_POSTGRES_ONLY_SKIP)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_migration_endpoint_hidden_outside_production(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    resp = client.post("/api/v1/migration/add-must-change-password-column", headers={"X-Migration-Secret": "anything"})
    assert resp.status_code == 404, resp.text


def test_migration_endpoint_rejects_missing_secret_env_var(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.delenv("MIGRATION_SECRET", raising=False)
    resp = client.post("/api/v1/migration/add-must-change-password-column", headers={"X-Migration-Secret": "guess"})
    assert resp.status_code == 403, resp.text


def test_migration_endpoint_rejects_wrong_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setenv("MIGRATION_SECRET", "the-real-secret")
    resp = client.post("/api/v1/migration/add-must-change-password-column", headers={"X-Migration-Secret": "wrong-guess"})
    assert resp.status_code == 403, resp.text


@_requires_postgres
def test_migration_endpoint_never_uses_jwt_auth_dependency(client, monkeypatch):
    """Confirm no Authorization header is required at all -- this is the whole point
    of not depending on get_current_user/login, which are broken until this column
    exists."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setenv("MIGRATION_SECRET", "the-real-secret")
    resp = client.post(
        "/api/v1/migration/add-must-change-password-column",
        headers={"X-Migration-Secret": "the-real-secret"},
        # deliberately no Authorization header
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["column"] == "must_change_password"
    assert body["verified"] is True


@_requires_postgres
def test_migration_endpoint_is_idempotent(client, monkeypatch):
    """Safe to call more than once -- the column already exists in this local dev
    database (auto_migrate_schema already added it), so this run itself proves
    idempotency: a second/Nth call must succeed identically, never error."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setenv("MIGRATION_SECRET", "the-real-secret")
    for _ in range(2):
        resp = client.post(
            "/api/v1/migration/add-must-change-password-column",
            headers={"X-Migration-Secret": "the-real-secret"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["verified"] is True


@_requires_postgres
def test_migration_endpoint_does_not_expose_secrets(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setenv("MIGRATION_SECRET", "the-real-secret")
    resp = client.post(
        "/api/v1/migration/add-must-change-password-column",
        headers={"X-Migration-Secret": "the-real-secret"},
    )
    assert "the-real-secret" not in resp.text
    assert "DATABASE_URL" not in resp.text
    assert "SECRET_KEY" not in resp.text
