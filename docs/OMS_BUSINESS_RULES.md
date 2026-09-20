# OMS Business Rules (Authoritative)

These are the manufacturing business rules already implemented and verified in this
system. This document does not introduce any new rule — it records what UAT and go-live
verification confirmed is actually enforced, with where enforcement lives. Any change to
these rules is a Class A/C change under `docs/OMS_CHANGE_CONTROL.md`, never an incidental
side effect of an unrelated fix.

1. **The OMS Engine is authoritative.** `backend/app/oms_core/oms_engine.py` and
   `backend/app/services/oms_integration_service.py` are the sole source of manufacturing
   calculations (yields, RAG status, stage targets, reconciliation). No second
   business-rule engine exists or should be introduced.

2. **The WO route is authoritative and per-WO.** Each Work Order's route is persisted in
   `WORoute` at release time (`OperationsService.release_work_order` /
   `OMSIntegrationService.initialize_wo_stages`) and every subsequent production/movement/
   dispatch action is validated against that specific WO's route — never a global
   constant. (`app/services/production_service.py`, `match_route_stage`.)

3. **Production transactions are immutable.** `ProductionUpdate` and `ProductionMovement`
   rows are only ever inserted, never updated or deleted. No API endpoint exists to edit
   or delete a posted transaction.

4. **Production input quantities are transaction deltas.** `RecordStageProductionRequest`/
   `MovePartsRequest` accept only the new quantity for that transaction; the backend adds
   it to the running `StageWIP` counters (`wip.ok_qty += req.good_qty`, etc.) rather than
   accepting or storing a cumulative figure. The Production Entry screen starts its
   quantity field blank on every load (fixed defect, see change log).

5. **Cumulative totals are display values only.** `ProductionEntryResponse` returns
   `stage_ok_total`/`stage_rejection_total` etc. purely for display; these are never
   accepted back as request input for a new transaction.

6. **Production and physical movement are separate events.** Completing production at a
   stage (`record_stage_production`) only updates that stage's OK/Reject counters; a
   distinct `move_parts` transaction is required to actually transfer material to the next
   stage, and can happen later or in different partial batches.

7. **Rejection never flows forward as good quantity.** `move_parts` only carries
   `quantity_moved` (explicitly separate from `rejected_quantity`) into the next stage's
   `ent_qty`; rejected pieces are recorded via `NCRecord` and stay attributed to the
   stage where they occurred.

8. **Cross-WO movement is prohibited.** `move_parts` rejects any request where
   `target_wo_number` differs from `wo_number` (`"Stage movement cannot cross Work
   Orders."`).

9. **Unauthorized stage jumping is prohibited.** `move_parts` requires the destination
   stage to be the immediate next stage in that WO's persisted route
   (`to_idx != from_idx + 1` → rejected).

10. **Dispatch cannot exceed eligible quantity.** `execute_dispatch` rejects any request
    where `dispatched_quantity > ready_for_dispatch_qty`, and — since the go-live BSR-gate
    fix — additionally rejects dispatch beyond what has actually entered BSR when the
    WO's route defines BSR as a distinct stage.

11. **Historical transactions are not recalculated using new master values.** The only
    "Conversion" feature (WO-to-WO quantity transfer) stores its resolved quantity once at
    transaction time and never re-derives it from a live master afterward. (No
    unit-of-measure conversion-factor master exists in this system to begin with — see
    known limitations in `docs/OMS_RELEASE_BASELINE.md`.)

12. **Idempotency prevents duplicate business transactions.** `client_request_id` carries
    a database-enforced unique constraint on `production_movements`, `production_updates`,
    `packing_transactions`, and `dispatches`; a repeated submission with the same token
    returns the original transaction instead of creating a second one.

13. **Concurrency controls prevent over-consumption.** `WorkOrder`, `StageWIP`, and
    `PackingRecord` rows are locked with `SELECT ... FOR UPDATE` (`with_for_update()`)
    before any read-modify-write of their quantities, on PostgreSQL.

14. **Audit history is immutable.** `AuditLog` rows are written for every significant
    mutation (production, movement, packing, dispatch, conversion, WO release) and no
    API endpoint exists to update or delete an audit log entry.

15. **ML/AI cannot modify manufacturing facts.** No code path in `app/analytics/*` or
    `app/services/ai_service.py` writes to any manufacturing table — verified by direct
    code inspection (no `db.add`/`db.commit`/`.update()` calls exist in either). See
    `docs/OMS_AI_ML_GOVERNANCE.md` for the full separation.
