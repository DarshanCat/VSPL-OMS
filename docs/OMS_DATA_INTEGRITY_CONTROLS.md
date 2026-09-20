# OMS Data Integrity Controls

For each control: what is protected, where it is enforced, how, and what happens when it
triggers. All controls listed here are already implemented and verified — this document
does not propose new ones.

## Quantity Validation
- **Protects**: against posting more OK+Reject than is actually available at a stage.
- **Where**: `ProductionService.record_stage_production`.
- **Enforcement**: `if total_proc > wip.available_wip: raise HTTPException(400, ...)`.
- **Failure behavior**: HTTP 400 with the exact available quantity in the message; nothing
  is written.

## WIP
- **Protects**: against WIP counters becoming inconsistent or negative.
- **Where**: `OMSIntegrationService.recompute_work_order`.
- **Enforcement**: in-process WIP is always `max(ent - ok - rej, 0)`; on-hand is always
  `max(ok - next_stage_ent, 0)` — floored at zero by construction.
- **Failure behavior**: WIP can never go negative; it floors at 0.

## Movement
- **Protects**: against moving more than is available, skipping stages, or moving into a
  non-adjacent stage.
- **Where**: `ProductionService.move_parts`.
- **Enforcement**: sequential-index check (`to_idx != from_idx + 1` → reject); available-WIP
  check (`total_consumed > from_wip.available_wip` → reject).
- **Failure behavior**: HTTP 400 naming the only valid next stage or the actual available
  quantity.

## Rejection
- **Protects**: against rejected material silently becoming "good" downstream.
- **Where**: `ProductionService.move_parts` / `record_stage_production` — `quantity_moved`
  and `rejected_quantity` are tracked as separate fields end to end; only `quantity_moved`
  feeds the next stage's `ent_qty`.
- **Failure behavior**: not applicable — this is a structural separation, not a rejectable
  validation.

## Packing
- **Protects**: against packing more than is pending, and against duplicate packing
  submissions.
- **Where**: `PackingService.update_packing`.
- **Enforcement**: `req.packed_quantity > packing_rec.pending_qty` → reject; `WorkOrder`
  and `PackingRecord` locked with `with_for_update()` before validation.
- **Failure behavior**: HTTP 400 naming the actual pending quantity.

## Dispatch
- **Protects**: against dispatching more than is ready, against crediting more than one
  StageWIP row for a single dispatch, and against bypassing a required BSR stage.
- **Where**: `DispatchService.execute_dispatch`.
- **Enforcement**: `dispatched_quantity > ready_for_dispatch_qty` → reject; only the WO's
  actual terminal route stage is credited (resolved via `WORoute`, not a hardcoded alias
  list); when BSR is a distinct stage in the route, cumulative dispatched quantity is
  additionally capped at what has actually entered BSR (`StageWIP.ent_qty`).
- **Failure behavior**: HTTP 400 with the specific shortfall.

## Idempotency
- **Protects**: against a double-click or network retry creating a duplicate business
  transaction.
- **Where**: `client_request_id` column with a database-enforced unique (partial, NULL-safe)
  index on `production_movements`, `production_updates`, `packing_transactions`, and
  `dispatches`; service-layer check-then-insert plus an `IntegrityError` fallback that
  returns the original transaction if a race is lost.
- **Failure behavior**: the duplicate call succeeds (HTTP 200) but returns the *original*
  transaction with a "Duplicate request detected" message — no new row, no quantity change.

## Concurrency
- **Protects**: against two simultaneous requests both succeeding against the same limited
  available quantity (oversell).
- **Where**: `WorkOrder`, `StageWIP`, and `PackingRecord` rows are fetched with
  `SELECT ... FOR UPDATE` (`with_for_update()`) before validation and mutation, in
  `ProductionService`, `PackingService`, and `DispatchService`.
- **Failure behavior**: on PostgreSQL, the second concurrent request blocks until the first
  commits, then re-validates against the now-current quantity (so it is correctly rejected
  if the quantity is no longer available). This guarantee depends on running against
  PostgreSQL — `with_for_update()` is a no-op on SQLite.

## Cross-WO Protection
- **Protects**: against material being recorded as moving into a different Work Order.
- **Where**: `ProductionService.move_parts`.
- **Enforcement**: `target_wo_number` must equal `wo_number` or the request is rejected.
- **Failure behavior**: HTTP 400 `"Stage movement cannot cross Work Orders."`.

## Route Enforcement
- **Protects**: against any action being posted for a stage that isn't part of that WO's
  actual released route.
- **Where**: `match_route_stage` (`oms_integration_service.py`), used by every production/
  movement endpoint.
- **Failure behavior**: HTTP 400 naming the WO's actual configured route.

## Master-Data History
- **Protects**: against a later master-data change silently altering historical
  transaction meaning.
- **Where**: the only such feature today (WO-to-WO Conversion) stores its resolved
  quantity once at transaction time; there is no unit-of-measure conversion-factor master
  in this system to begin with (see `docs/OMS_RELEASE_BASELINE.md` known limitations).

## Audit
- **Protects**: against an untraceable or alterable manufacturing history.
- **Where**: `AuditLog`, written by every mutating service method; no update/delete
  endpoint exists for it.
- **Failure behavior**: not applicable — this is a write-only, append-only log.
