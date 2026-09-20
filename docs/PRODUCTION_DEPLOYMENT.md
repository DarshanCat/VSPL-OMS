# OMS Production Deployment Guide

Scope: the existing VSPL SMES + OMS system (FastAPI backend, Next.js frontend, PostgreSQL).
This document does not introduce new infrastructure — it describes how to run what already
exists in this repository.

## 1. Prerequisites

- PostgreSQL 16 (see `backend/docker-compose.yml` for a local reference instance)
- Python 3.11+ (backend)
- Node.js 20+ (frontend)
- A reverse proxy / TLS terminator in front of both services (not included in this repo)

## 2. Environment Variables

### Backend (`backend/.env`, see `backend/.env.example`)

| Variable | Purpose | Production requirement |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | Must point at the production database, e.g. `postgresql://user:pass@host:5432/vspl_smes` |
| `REDIS_URL` | Present in config; no code path currently uses it (see §13) | Safe to leave default |
| `SECRET_KEY` | JWT signing secret | **Required.** The app refuses to start if `ENVIRONMENT=production` and this is still the shipped default — generate a unique long random value (e.g. `openssl rand -hex 32`) |
| `ALGORITHM` | JWT algorithm | Leave as `HS256` unless changed deliberately |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Session length | Tune per company policy |
| `ENVIRONMENT` | `development` / `production` | Must be `production` to enable the `SECRET_KEY` safety check |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend origins | Set to the exact production frontend URL(s), e.g. `https://oms.vspl.example` — do not use `*` |

### Frontend (`frontend/.env.local`, see `frontend/.env.example`)

| Variable | Purpose | Production requirement |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Base URL the browser calls for the backend API | Must be the public backend URL, e.g. `https://api.vspl.example` (defaults to `http://localhost:8000` if unset — do not deploy with the default) |

Never commit real values for any of the above. Only variable **names** belong in `.env.example`.

## 3. Database — Backup, Migrate, Verify, Rollback

This project does not drive schema changes through Alembic in practice — the Alembic
revisions under `backend/alembic/versions/` are empty scaffolding. The real, currently-used
migration mechanism is `app.core.database.auto_migrate_schema()`, which runs automatically
on backend startup (`app/main.py` lifespan) and applies only additive, idempotent statements
(`CREATE TABLE IF NOT EXISTS` via `Base.metadata.create_all()`, then `ADD COLUMN IF NOT EXISTS`
/ `CREATE UNIQUE INDEX IF NOT EXISTS` statements). It contains no destructive statements
(no `DROP`, no `TRUNCATE`, no `DELETE`).

**BACKUP → MIGRATE → VERIFY → SMOKE TEST → GO LIVE**

1. **Backup** (always, before every deploy):
   ```bash
   pg_dump -Fc "$DATABASE_URL" -f vspl_smes_$(date +%Y%m%d_%H%M%S).dump
   ```
2. **Migrate**: schema changes apply automatically the moment the new backend process
   starts (see mechanism above). There is no separate migration command to run by hand.
3. **Verify**: confirm the backend started cleanly and the new columns/tables/indexes exist:
   ```bash
   curl -f https://api.vspl.example/health
   psql "$DATABASE_URL" -c "\d stage_wips" # spot-check a table touched by this release
   ```
4. **Smoke test**: see `docs/PRODUCTION_SMOKE_TEST.md`.
5. **Go live**: point the reverse proxy / release traffic at the new instance.

**Rollback:**
- **Migration/startup fails**: the backend process will fail to boot (e.g. the
  `SECRET_KEY` guard raises `RuntimeError`, or a DB connection error). Nothing in
  `auto_migrate_schema()` is destructive, so the previous database state is untouched —
  redeploy the previous backend image/commit against the same database.
- **Application startup fails for other reasons**: redeploy the previous known-good
  commit/tag (`oms-v1.0.0`); no database changes need to be reverted since the schema
  changes are additive.
- **Database connectivity fails**: verify `DATABASE_URL`, network/security group rules,
  and that PostgreSQL is accepting connections; the backend will not serve traffic
  (`/health` will fail) until connectivity is restored — no data-integrity risk from this
  in itself.
- **A critical manufacturing transaction fails mid-flight**: every production/movement/
  packing/dispatch write happens inside a single DB transaction per request and is only
  committed on success (see `ProductionService`, `PackingService`, `DispatchService`) — a
  failed request leaves no partial row. If a specific WO's data looks wrong, use
  `OMSIntegrationService.reconcile_work_order` (exposed via the reconciliation
  endpoints) to compare `Released Qty` against `Total WIP + Rejected + Dispatched`
  before taking any corrective action, and restore from the pre-deploy `pg_dump` only as
  a last resort.

## 4. Backend Deployment

Entry point: `backend/app/main.py` (`app`), an existing FastAPI application — no new entry
point was introduced.

```bash
cd backend
python -m venv venv && source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env   # then fill in real production values
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Do not pass `--reload` in production. Run behind a reverse proxy that terminates TLS.

On startup the app: creates any missing tables, applies additive column/index migrations,
and seeds demo/bootstrap accounts **only if they don't already exist** (existing accounts'
passwords and roles are never touched by this — see §15).

Health check: `GET /health` (already existed; not duplicated).

FastAPI's default `debug=False` behavior is in effect (not overridden anywhere in
`main.py`), so unhandled exceptions return a generic 500 to the client and do not leak
stack traces; the traceback is only visible in the server's own stderr/uvicorn logs.

## 5. Frontend Deployment

```bash
cd frontend
npm install
npm run build
npm start   # serves the production build; configure your process manager/reverse proxy in front of it
```

Confirm `NEXT_PUBLIC_API_URL` is set to the real backend URL at build time (Next.js
inlines `NEXT_PUBLIC_*` variables at build time, so it must be set **before** `npm run build`,
not just at runtime).

## 6. Logging & Monitoring

No custom application logging or monitoring platform exists in this codebase, and none is
introduced here (per the "do not introduce new infrastructure" constraint). In production:
- Backend: capture uvicorn's stdout/stderr (request access logs + any unhandled exception
  tracebacks) via your process manager / container runtime's log driver.
- Frontend: capture `next start`'s stdout/stderr the same way.
- Do not enable verbose SQL echo (`echo=True` is not set anywhere) or any setting that
  would print credentials/tokens — none currently exists.

## 7. Background Jobs

None. `celery` and `redis` appear in `requirements.txt` / `config.py` (`REDIS_URL`) but no
task, worker, or scheduler is defined or imported anywhere in `app/`. The only
OMS-engine batch operation (`oms_engine.run()`) is triggered on demand via
`POST /api/v1/oms/run-cycle`, not on a schedule. There is nothing to start, monitor, or
worry about if "stopped" — there is no running background process today.

## 8. Admin Setup

See `docs/PRODUCTION_SMOKE_TEST.md` for the post-deploy checklist and the main UAT report
for the full role list. In short: `seed_database_if_empty()` creates a fixed set of demo
accounts (one per role) only the first time it runs against an empty `users` table.
`POST /api/v1/auth/register` requires an existing ADMIN token, so no one else can create
further accounts. **Rotate every seeded account's password immediately after first
production login** — the seed credentials are public (they are in this repository's
source code).

## 9. Release Version

- Tag: `oms-v1.0.0`
- See release commit/date recorded in the final release report delivered alongside this
  document.
