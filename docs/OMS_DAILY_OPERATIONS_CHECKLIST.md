# OMS Daily Operations Checklist

Use the existing OMS reconciliation logic and endpoints for every check below — never a
new formula.

## Start of Day

- [ ] Application health — `GET /health` returns 200
- [ ] Database health — health check succeeds (it depends on a live DB connection); or
      `SELECT 1` against `DATABASE_URL` directly
- [ ] Authentication — a known account can log in and receive a valid token
- [ ] Critical API health — `GET /api/v1/dashboard/stats`, `GET /api/v1/work-orders`,
      `GET /api/v1/production/wip` all return 200 with an authenticated request
- [ ] Production transaction availability — `POST /api/v1/production/entry` accepts a
      valid request against a known WO/stage (verify on a non-production/test WO if one
      exists; do not post throwaway transactions against real WOs)
- [ ] Active WO availability — `GET /api/v1/work-orders` lists the expected active WOs
- [ ] Route availability — spot-check `GET /api/v1/work-orders/{wo}/route` for a couple of
      active WOs

## During Day

- [ ] Production transactions — spot-check recent entries look correct (right stage, right
      user, plausible quantity)
- [ ] Movement transactions — no unexpected rejections in logs beyond legitimate business
      rejections (over-quantity, stage-jump, cross-WO)
- [ ] Quality transactions — rejections are being recorded with a reason/defect code
- [ ] Packing — partial packing totals look correct
- [ ] BSR (where applicable) — dispatch is not succeeding on BSR routes without an actual
      PACKING→BSR movement having occurred
- [ ] Dispatch — no over-dispatch rejections indicate a real operational block (as opposed
      to a legitimate "already fully dispatched" rejection)
- [ ] Error monitoring — periodically check backend stdout/stderr for `ERROR`, `CRITICAL`,
      `Traceback`, `DatabaseError`, `IntegrityError` (see `docs/OMS_SUPPORT_RUNBOOK.md`
      "Observability baseline")

## End of Day

- [ ] WIP reconciliation — `GET /api/v1/production/reconciliation` shows
      `is_plant_balanced: true`; investigate any WO where `is_balanced: false`
- [ ] Production reconciliation — for each active WO, `Released Qty == Total WIP +
      Rejected + Dispatched` (the same reconciliation call reports this per WO)
- [ ] Rejection review — check `GET /api/v1/operations/nc` for open NC records needing
      disposition
- [ ] Packing review — `GET /api/v1/packing/queue` for anything stuck pending longer than
      expected
- [ ] Dispatch review — `GET /api/v1/dispatch/queue` and `/history` for the day's activity
- [ ] Exception review — any P0/P1/P2 raised during the day per
      `docs/OMS_SUPPORT_RUNBOOK.md` severity definitions
- [ ] Audit review — `GET /api/v1/admin/audit-logs` (ADMIN/PRODUCTION_MANAGER/QA/CEO only)
      spot-checked for the day's significant mutations
- [ ] Backup verification — confirm the day's scheduled backup actually completed (see
      `docs/OMS_BACKUP_RECOVERY.md`); this is an infrastructure check, not an OMS API call
