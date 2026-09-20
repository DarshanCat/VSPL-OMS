# OMS Audit Readiness

This document verifies, against the actual implementation, that the system can answer the
standard manufacturing-audit questions for any transaction.

## What the system can demonstrate today

| Question | Answered by | Verified |
|---|---|---|
| Who performed a transaction | `AuditLog.user_id` / `user_name`, and `operator_id`/`operator_name`/`created_by` on the underlying ledger row | Yes — confirmed present on production, movement, packing, dispatch |
| What was performed | `AuditLog.action` (`STAGE_PRODUCTION_ENTRY`, `PRODUCTION_MOVE`, `PACKING_UPDATE`, `DISPATCH_GOODS`, `CONVERSION`, `WO_RELEASE`, NC actions) | Yes |
| When it happened | `AuditLog.created_at` (server-side timestamp) plus the ledger row's own `created_at`/`movement_date`/`movement_time` | Yes |
| Which WO was involved | `AuditLog.entity_id` (WO number) and `work_order_id` on every ledger row | Yes |
| Which stage was involved | `stage`/`from_stage`/`to_stage` on the relevant ledger row | Yes |
| Quantity | `good_qty`/`reject_qty`/`quantity_moved`/`packed_quantity`/`dispatched_qty` on the relevant ledger row | Yes |
| Rejection (where applicable) | `NCRecord` (defect code, root cause, disposition, responsibility) linked to the WO and stage | Yes |
| Movement history | `production_movements` table, immutable, queryable via `GET /api/v1/production/movements` | Yes |
| Packing history | `packing_transactions` table (added at go-live to close a gap where only an aggregate existed) | Yes |
| Dispatch history | `dispatches` table, queryable via `GET /api/v1/dispatch/history` | Yes |
| Relevant master-data changes | **Gap** — there is currently no write/update/delete endpoint for master data (`Customer`, `Part`) at all, so there is nothing to audit yet; if master-data write endpoints are added in the future (a Class E change), an audit requirement must be part of that change's design from the start |

## Immutability verification

- No API endpoint exists to `PUT`/`PATCH`/`DELETE` a production entry, movement, packing
  transaction, or dispatch record (confirmed by inspecting every router in
  `backend/app/api/v1/`).
- No API endpoint exists to modify or delete an `AuditLog` row (`admin.py` only exposes a
  `GET`).
- Corrections are made by posting new, correctly-attributed transactions, never by
  altering history — see `docs/OMS_SUPPORT_RUNBOOK.md` Case 3.

## Access control on audit data

`GET /api/v1/admin/audit-logs` is restricted to `ADMIN`, `PRODUCTION_MANAGER`, `QA`, and
`CEO` roles (fixed during the production-handover review; previously open to any
authenticated user).

## Rule

**Do not modify historical data merely to make an audit report look cleaner.** If a report
looks wrong, investigate whether it's a genuine defect (fix the reporting code, never the
historical rows) or a real historical event that simply needs explaining in the report's
narrative.
