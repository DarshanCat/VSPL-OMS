# OMS Release Baseline

This document is the approved production baseline. Any change to the system must be made
against this baseline through the process in `docs/OMS_CHANGE_CONTROL.md`.

## Architecture Version
`oms-v1.0.0` — FastAPI/SQLAlchemy backend, Next.js frontend, PostgreSQL database, the
existing deterministic OMS Engine (`backend/app/oms_core/oms_engine.py`) and
`OMSIntegrationService` (`backend/app/services/oms_integration_service.py`) as the sole
authoritative business-rule layer. No second business-rule engine, no ORM other than
SQLAlchemy, and no DC (Delivery Challan) functionality exist in this system.

## Backend Version
- Git tag: `oms-v1.0.0`
- Commit: `3cb9c41beb9904a61b020d922d9fd96579bc7b86`
- Framework: FastAPI, SQLAlchemy 2.x, Pydantic v2
- Entry point: `backend/app/main.py` (`app`)

## Frontend Version
- Same commit/tag as backend (monorepo, single release)
- Framework: Next.js 15 (App Router), React 18, TypeScript

## Database Version
- PostgreSQL 16 in production (SQLite fallback for local dev only)
- Schema is created and evolved by `app.core.database.auto_migrate_schema()`, which runs
  automatically on backend startup and applies only additive statements (`CREATE TABLE`/
  `COLUMN`/`INDEX IF NOT EXISTS`). Alembic revisions under `backend/alembic/versions/` are
  empty scaffolding and are **not** the mechanism actually driving schema changes — this is
  a known characteristic of the current baseline, not a defect to silently "fix" by
  switching mechanisms (that would be a change-control item, not a stabilization task).
- Tables at this baseline: `users`, `customers`, `parts`, `orders`, `work_orders`,
  `wo_routes`, `stage_wips`, `production_movements`, `production_updates`,
  `packing_records`, `packing_transactions`, `dispatches`, `nc_records`, `conversions`,
  `audit_logs`.

## Important Configuration
| Variable | Where | Notes |
|---|---|---|
| `DATABASE_URL` | backend | Must point at production PostgreSQL |
| `SECRET_KEY` | backend | App refuses to start if `ENVIRONMENT=production` and this is left at the shipped default |
| `ENVIRONMENT` | backend | Must be `production` to enable the `SECRET_KEY` safety check |
| `CORS_ORIGINS` | backend | Comma-separated allowed frontend origin(s); no wildcard |
| `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | backend | JWT settings |
| `NEXT_PUBLIC_API_URL` | frontend | Backend URL the browser calls; must be set before `next build` (inlined at build time) |

See `backend/.env.example` and `frontend/.env.example` for the full, current variable names.

## Current Known Limitations
- WO release, conversion, dispatch, and NC disposition are now role-restricted (security
  hardening, see `docs/OMS_CHANGE_CONTROL.md` log). Production entry, movement, packing,
  and order intake remain open to any authenticated role beyond "must be authenticated" —
  closing this further requires a business decision on the intended role matrix, not an
  engineering guess. See `docs/OMS_PRODUCTION_DATA_ACCESS.md` for the current, exact
  enforcement table.
- No unit-of-measure (e.g. KG↔PCS) conversion-factor master exists. The only "Conversion"
  feature is a WO-to-WO quantity split, which is already immutable per transaction.
- `celery` and `redis` are present as dependencies/config but nothing in the application
  uses them — there are no background jobs or scheduled tasks in this system.
- No automated, scheduled database backup exists inside this repository/environment;
  backups must be run through your actual infrastructure's own mechanism (see
  `docs/OMS_BACKUP_RECOVERY.md`).
- No custom application logging/monitoring platform exists; operational visibility comes
  from the ASGI server's (uvicorn's) own stdout/stderr and the `/health` endpoint.
- Lint (`eslint`) is configured (`frontend/eslint.config.mjs`) but not installed as a
  dependency.

## Current Non-Blockers
All items above are documented, accepted operating constraints of this baseline — none
block production use. They should only be closed through the change-control process in
`docs/OMS_CHANGE_CONTROL.md`, not by ad hoc engineering changes.
