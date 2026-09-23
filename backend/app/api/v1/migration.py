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
from app.core.database import engine

router = APIRouter(prefix="/api/v1/migration", tags=["migration"])


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
