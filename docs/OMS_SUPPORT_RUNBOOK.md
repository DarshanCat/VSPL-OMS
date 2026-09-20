# OMS Support Runbook

## Observability baseline (what actually exists — nothing more)

- **Health endpoint**: `GET /health` on the backend.
- **Application logs**: uvicorn's own stdout/stderr (request access logs, and any
  unhandled exception traceback). No custom logging framework or log aggregation exists.
- **Database logs**: whatever your PostgreSQL server/host itself provides — not something
  this application configures.
- **Error monitoring**: none beyond reading process logs; no external error-tracking
  service is integrated.
- **Backup monitoring**: none automated inside this repository — see
  `docs/OMS_BACKUP_RECOVERY.md`.
- **Deployment information**: git tag/commit (`docs/OMS_RELEASE_BASELINE.md`).

Do not assume a monitoring platform exists beyond what is listed above. Introducing one is
a Class E change.

## Incident Severity

- **P0** — Critical data corruption, security issue, or manufacturing-integrity failure
  (e.g. double-dispatch, cross-WO movement succeeding, an authentication bypass).
- **P1** — Major manufacturing workflow failure (e.g. a stage cannot post production at
  all, dispatch is completely blocked plant-wide).
- **P2** — Important operational issue with a workaround (e.g. a confusing but non-blocking
  error message).
- **P3** — Minor/non-blocking issue (e.g. a cosmetic UI inconsistency).

For **P0/P1**: stop the affected operation if continuing would cause further incorrect
data, preserve evidence (do not delete or edit anything), escalate immediately, and do not
manually manipulate manufacturing records while investigating.

## Case 1 — Production transaction failed

Check, in this order:
1. The API response body — the backend returns a specific reason (e.g. "Only 40 pieces are
   available at stage X").
2. Backend logs for that request's timestamp.
3. The WO's current state and route (`GET /api/v1/work-orders/{wo}/tracking` and `/route`).
4. The stage and its `available_wip` (`GET /api/v1/production/wip`).
5. The submitting user's role/permissions.

**Do not manually change database quantities.** If the rejection was correct (the operator
really did request more than available), it is not a defect — it's the system working as
designed.

## Case 2 — Movement failed

Check:
1. Source stage's `available_wip`.
2. Destination stage — is it actually the *next* stage in this WO's persisted route?
3. The WO's route (`GET /api/v1/work-orders/{wo}/route`).
4. Whether `target_wo_number` matches `wo_number` (cross-WO movement is always rejected).
5. Whether a `client_request_id` was reused unintentionally (check for a "Duplicate
   request detected" message — that is expected idempotency behavior, not a failure).

## Case 3 — Wrong quantity entered

**Do not edit the ledger directly.** Production, movement, packing, and dispatch records
are immutable by design (see `docs/OMS_BUSINESS_RULES.md` #3). Use the existing
correction/NC/reconciliation process: post a new, correctly-attributed transaction (e.g. an
NC record for a missed rejection, or a subsequent production/movement entry), and verify
the WO balances afterward via the reconciliation endpoint. If the existing process cannot
actually represent the correction needed, document the specific gap and raise it as a
Class A/E change request — do not invent a workaround.

## Case 4 — Duplicate submission

Check:
1. The `client_request_id` used by the client for both attempts.
2. The relevant ledger table (`production_movements`, `production_updates`,
   `packing_transactions`, `dispatches`) for that token — there should be exactly one row.
3. The audit log for that WO/action — there should be exactly one audit entry per real
   transaction.

**Do not delete records.** If a genuine duplicate is found (two *different* tokens somehow
representing the same real-world transaction, e.g. an operator posted twice by hand because
they thought the first attempt failed), determine root cause (user/process issue vs.
software defect) before doing anything. If it is a software defect (the idempotency
mechanism failed to catch it), that is a P0/P1 — escalate and follow
`docs/OMS_CHANGE_CONTROL.md`. If it is a user/process issue, resolve it via the correction
process, not a direct edit.

## Case 5 — Dispatch mismatch

Check:
1. `PackingRecord` for the WO — `packed_qty`, `pending_qty`, `ready_for_dispatch_qty`,
   `dispatched_qty`.
2. If the WO's route includes BSR as a distinct stage: has the material actually been
   moved from PACKING into BSR (`StageWIP.ent_qty` for the BSR stage)? Dispatch is blocked
   until it has.
3. The WO's actual terminal stage per its route (should be `DISPATCH`) — only that single
   `StageWIP` row should ever be credited by a dispatch.
4. Dispatch history (`GET /api/v1/dispatch/history`) for duplicate invoice numbers or
   unexpected quantities.
5. The WO's route to confirm what stages actually precede dispatch for that specific WO.

## Case 6 — User cannot access a function

Check, backend first:
1. The user's `role` (`users.role` — one of `ADMIN`, `CEO`, `PRODUCTION_MANAGER`,
   `PLANNER`, `QA`, `DISPATCH`, `MACHINE_OPERATOR`, `OPERATOR`, `PACKING`, `STORE`,
   `SALES`).
2. Whether the endpoint they're calling actually enforces a role restriction
   (`require_roles(...)` in the relevant `app/api/v1/*.py` router) — most endpoints today
   only require authentication, not a specific role (see
   `docs/OMS_PRODUCTION_DATA_ACCESS.md`).
3. The actual HTTP status returned (401 = not authenticated, 403 = authenticated but wrong
   role).
4. Only after confirming backend behavior is correct, check whether the frontend is hiding
   or disabling something incorrectly — **a hidden button is never the actual security
   control**, the backend check is.

## Case 7 — Database issue

**Do not manually manipulate manufacturing records.** If the database is unreachable,
corrupted, or behaving unexpectedly:
1. Confirm `DATABASE_URL` and network connectivity first.
2. Check `/health` — it will fail if the DB is unreachable.
3. Escalate using the backup/recovery procedure in `docs/OMS_BACKUP_RECOVERY.md`. Do not
   attempt ad hoc SQL fixes against production data.
