"""ONE-TIME production schema migration for users.must_change_password.

Why this exists as a separate mechanism instead of reusing normal admin auth:
/auth/login and get_current_user (app/api/deps.py) both load the full User ORM
entity, which is exactly the column this migration adds -- until the column exists,
those paths themselves raise psycopg2.errors.UndefinedColumn. That makes ordinary
JWT-based admin authorization circular and unusable here: nobody, including a real
admin, can obtain a fresh token while this bug is live. Authorization is instead a
constant-time comparison against MIGRATION_SECRET, a dedicated environment variable
set only for this one-time operation.

Deliberately NOT idempotent-forever by design of process, only by SQL: safe to call
more than once (ADD COLUMN IF NOT EXISTS), but this file, its router registration,
and the MIGRATION_SECRET environment variable are all meant to be removed once the
migration is confirmed -- see docs/PRODUCTION_DEPLOYMENT.md or the commit history
for the removal step.
"""
import os
import secrets
from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import text
from app.core.config import settings
from app.core import database as db_core
from app.core.database import engine, Base, auto_migrate_schema, LIFESPAN_STATUS

router = APIRouter(prefix="/api/v1/migration", tags=["migration"])


def _require_migration_secret(x_migration_secret: str):
    """Shared gate for every endpoint in this router: hidden entirely outside
    production, and a constant-time comparison against MIGRATION_SECRET otherwise --
    the same authorization model already used by add-must-change-password-column."""
    if settings.ENVIRONMENT.lower() != "production":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    expected = os.environ.get("MIGRATION_SECRET")
    if not expected or not secrets.compare_digest(x_migration_secret or "", expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.post("/add-must-change-password-column")
def add_must_change_password_column(x_migration_secret: str = Header(default="")):
    if settings.ENVIRONMENT.lower() != "production":
        # Hide even the existence of this endpoint outside production.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    expected = os.environ.get("MIGRATION_SECRET")
    if not expected or not secrets.compare_digest(x_migration_secret or "", expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password "
            "BOOLEAN NOT NULL DEFAULT FALSE;"
        ))
        verified = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'must_change_password';"
        )).first() is not None

    if not verified:
        raise HTTPException(status_code=500, detail="Migration did not take effect.")

    return {"success": True, "column": "must_change_password", "verified": True}


@router.get("/status")
def schema_sync_status(x_migration_secret: str = Header(default="")):
    """READ-ONLY diagnostic. Reports whether this running process's lifespan startup
    has executed and what the last schema-sync attempt found -- never secrets, never
    business data, never a row of application data. Exists because the app.main
    lifespan (Base.metadata.create_all() + auto_migrate_schema()) was found to never
    run at all under the Vercel mount architecture until vercel_entry.py's fix; this
    lets that be verified directly against a live deployment instead of assumed."""
    _require_migration_secret(x_migration_secret)

    return {
        "lifespan_started_at": LIFESPAN_STATUS["started_at"],
        "create_all_ran": LIFESPAN_STATUS["create_all_ran"],
        "schema_sync_last_result": db_core.SCHEMA_SYNC_LAST_RESULT,
    }


@router.post("/sync-schema")
def sync_schema(x_migration_secret: str = Header(default="")):
    """Manual, on-demand fallback for the exact same additive-only schema sync the
    app lifespan already performs on every normal startup (Base.metadata.create_all()
    -- creates only entirely-missing tables, never touches an existing one -- then
    auto_migrate_schema() -- ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
    only, per-statement, never DROP/TRUNCATE/DELETE). Not a second mechanism: it
    calls the identical functions, so its safety guarantees are identical. Exists so
    schema sync can be triggered explicitly if a given deployment's lifespan turns
    out not to run for any reason, without needing a code change or redeploy to fix
    it -- 'do not assume the startup mechanism works' extended to future deployments
    too, not just this one investigation.

    Idempotent: safe to call any number of times. Returns only counts (attempted/
    succeeded/failed) and the dialect name -- never a statement's SQL, never a
    credential, never a row of business data."""
    _require_migration_secret(x_migration_secret)

    Base.metadata.create_all(bind=engine)
    result = auto_migrate_schema()

    return {"success": True, "schema_sync": result}
