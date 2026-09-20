# OMS Go-Live Handover

## 1. Production URL
Not assigned in this repository/environment. Record your actual production frontend and
backend URLs here once deployed to your real infrastructure (this session verified the
release against a local rehearsal environment only — see §4).

## 2. Release Version
`oms-v1.0.0`

## 3. Release Commit
`f93ec26` (branch `claude/oms-uat-production-handover-95a6fa`)

## 4. Deployment Date/Time
2026-09-20 — controlled go-live rehearsal performed in a sandboxed environment against a
fresh, isolated PostgreSQL 16 instance and a production-mode (`next build && next start`)
frontend build, since this session has no access to your real production servers/domain.
**Before going live on your actual infrastructure**, follow `docs/PRODUCTION_DEPLOYMENT.md`
and re-run `docs/PRODUCTION_SMOKE_TEST.md` against that real environment.

## 5. Backend Status
Verified in this session:
- Clean startup against real PostgreSQL, no exceptions, no secrets in logs
- `GET /health` → `200 {"status":"online"}`
- Authentication, RBAC, CORS all verified at the API level
- Full manufacturing cycle exercised live: intake → release → production → movement →
  rejection → packing → BSR → dispatch → reconciliation, all balanced with zero variance
- 48/48 automated tests pass

## 6. Frontend Status
- Production build (`npm run build`) clean, TypeScript clean
- Served in production mode (`npm start`), login and dashboard verified in a live browser
  session against the real backend API, no console errors

## 7. Database Status
- Schema created automatically on backend startup (`Base.metadata.create_all()` +
  `auto_migrate_schema()` — additive only, no destructive statements)
- All expected tables, indexes and constraints confirmed present on real PostgreSQL
  (verified via `\dt` / `\d <table>` during rehearsal)
- Migration mechanism note: Alembic revisions under `backend/alembic/versions/` are empty
  scaffolding and are **not** the mechanism actually driving schema changes — see
  `docs/PRODUCTION_DEPLOYMENT.md` §3 for the real procedure

## 8. Health Check
`GET /health` on the backend. No separate/duplicate health architecture was introduced.

## 9. User Roles
`ADMIN`, `CEO`, `PRODUCTION_MANAGER`, `PLANNER`, `QA`, `DISPATCH`, `MACHINE_OPERATOR`,
`OPERATOR`, `PACKING`, `STORE`, `SALES` (see `backend/app/models/user.py`). Seeded demo
accounts (one per major role) exist for first login only — **rotate every seeded
password immediately** (they are public, being in this repository's source).
`POST /api/v1/auth/register` requires an existing ADMIN session, so only an admin can
create further accounts.

## 10. Basic Operating Workflow
```
OAR / Order Intake → Work Order → WO Release (with route) → Production Entry (per stage)
→ Movement (stage to stage, sequential only) → Quality/Rejection (isolated, never forwarded)
→ Packing → BSR (only if the WO's route includes it) → Dispatch → Analytics/Reconciliation
```
See `docs/OMS_OPERATOR_QUICK_GUIDE.md` for the floor-level walkthrough.

## 11. Backup Procedure
```bash
pg_dump -Fc "$DATABASE_URL" -f vspl_smes_$(date +%Y%m%d_%H%M%S).dump
```
Full detail in `docs/PRODUCTION_DEPLOYMENT.md` §3.

## 12. Rollback Procedure
- **Application**: redeploy the previous release commit/tag; schema changes are additive
  only, so no database rollback is required alongside an application rollback.
- **Database**: restore from the most recent `pg_dump` only if data itself needs reverting
  (not needed for a simple bad-deploy rollback). Full detail in
  `docs/PRODUCTION_DEPLOYMENT.md` §3.

## 13. Known Non-Blockers
- No business-defined RBAC matrix exists for production/packing/dispatch endpoints beyond
  "must be an authenticated user" — any role can currently perform these floor-execution
  actions. Not fixed because guessing the intended matrix risks breaking legitimate
  workflows; needs a business decision.
- No KG↔PCS (or similar) unit-of-measure conversion-factor master exists in this codebase.
  The only "Conversion" feature is a WO-to-WO quantity split, which is already immutable
  per transaction.
- `celery` and `redis` are listed as dependencies but nothing in the application actually
  uses them — there are no background jobs or scheduled tasks to monitor.
- Lint (`eslint`) is configured (`eslint.config.mjs`) but not installed as a dependency;
  not run, per instructions not to install unrelated tooling.
- Concurrency protection (row locking) was verified via sequential idempotency/oversell
  checks, not a true multi-threaded/multi-process stress test.

## 14. Support / Troubleshooting
- **Backend won't start**: check `ENVIRONMENT`/`SECRET_KEY` (the app deliberately refuses
  to start in production with the default secret) and `DATABASE_URL` connectivity first.
- **500 errors**: the client only ever sees a generic message; the real traceback is in
  the backend process's own stdout/stderr — check there first.
- **A WO's numbers look wrong**: use the reconciliation endpoint/report
  (`OMSIntegrationService.reconcile_work_order` / `GET /api/v1/production/reconciliation`)
  to compare `Released Qty` against `WIP + Rejected + Dispatched` before touching anything.
- **Suspected duplicate transaction**: check the relevant ledger table
  (`production_movements`, `production_updates`, `packing_transactions`, `dispatches`) for
  the `client_request_id` used — a duplicate submission with the same id is expected to be
  deduplicated automatically, not create a second row.
- See also `docs/PRODUCTION_DEPLOYMENT.md` for environment/migration/deployment detail and
  `docs/PRODUCTION_SMOKE_TEST.md` for the full post-deploy verification checklist.
