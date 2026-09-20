# OMS Operator Quick Guide

## Before you start: the one rule that matters most

**Every quantity field you type into Production, Movement, Packing, or Dispatch is a NEW
transaction amount — not a running total.**

If you complete 30 pieces, type `30`. If you later complete another 20, type `20` again —
not `50`. The system adds these up for you and shows you the running totals separately.
Typing a running total by mistake will record far more production than actually happened.

## 1. Login
Go to the SMES login page, enter your email and password, and sign in. Your role
determines which screens and actions you can use.

## 2. Find Work Order
Use the WO search/lookup box (accepts a WO number or barcode scan) on any production
screen to load a specific Work Order.

## 3. View Route
Once a WO is loaded, its authoritative route (e.g. F1 → F2 → F3 → FI → PACKING → DISPATCH)
is shown with the current stage highlighted. This route is fixed for that WO — you cannot
skip a stage or use a different order.

## 4. Enter Production
On the Production Entry screen, enter the **OK Completed Quantity** and **Rejected
Quantity** for what you just finished at your stage — fresh numbers only (see the rule
above). The field starts blank every time; do not carry over a previous number.

## 5. Record Rejection
Enter the rejected/scrap quantity in the same production entry alongside the OK quantity.
A rejection reason/defect code may be required. Rejected pieces never count as good and
will not move forward to the next stage.

## 6. Move Parts
Use "Move Parts" to physically transfer completed pieces from your stage to the next
stage in the route. You can move a partial quantity, and you can move the rest later in a
separate transaction. You cannot move material to a stage other than the next one in the
route, and you cannot move material into a different Work Order.

## 7. Perform Quality
Quality/NC actions are recorded the same way — against the specific stage and quantity
where the rejection occurred. Do not batch multiple days of rejections into one entry.

## 8. Pack
On the Packing screen, enter the quantity you are packing right now (again, a fresh
delta, not a cumulative count). You can pack in multiple batches.

## 9. BSR (where applicable)
If — and only if — the Work Order's route includes a BSR stage, you must move the packed
material into BSR before it can be dispatched. If BSR is not part of that WO's route, skip
it entirely; the system will not ask for it.

## 10. Dispatch
Enter the quantity being dispatched under the relevant invoice. Partial dispatches are
supported. You cannot dispatch more than what is actually ready (packed, and cleared
through BSR if applicable).

## 11. View History
Use the Movement History / Production History / Dispatch History screens to see every
individual transaction ever posted for a WO — these records are permanent and cannot be
edited or deleted from the UI.

## 12. What to do if a transaction fails
Read the error message — it will tell you exactly why (e.g. "only 40 pieces available",
"cannot skip a stage", "already dispatched"). Correct the quantity or stage and resubmit.
If you are unsure why it failed, stop and ask your supervisor/admin rather than trying
different numbers until one is accepted.

## 13. What NOT to do
- Do **not** re-enter a cumulative/running total into a new transaction — always enter the
  fresh amount for that transaction only.
- Do **not** try to move material to a stage other than the next one in the route.
- Do **not** try to move material between two different Work Orders.
- Do **not** ask an administrator to manually edit a production/movement/packing/dispatch
  record to "fix" a mistake — see the Support Rules below.
- Do **not** submit the same transaction twice on purpose to "double it up" — the system
  will detect and ignore an exact duplicate, but never rely on this instead of entering the
  correct quantity the first time.

---

## Support Rules (for admins and supervisors)

1. **Never** manually edit production ledger records (production entries, movements,
   packing transactions, dispatches) directly in the database.
2. **Never** delete a manufacturing transaction to "correct" a mistake.
3. **Use the approved correction/NC/reconciliation process** — post an offsetting/
   corrective transaction through the normal screens, and use the reconciliation report to
   confirm the WO balances afterward. Do not try to "undo" history.
4. **Do not bypass RBAC** — do not share admin credentials or elevate a user's role to work
   around a permission you think is wrong; raise it as a change request instead.
5. **Do not manually modify database quantities** for any reason, including "just this
   once" for a demo or a rush order.
6. **Do not move material between Work Orders** — if material genuinely needs to be
   reassigned, use the existing Conversion feature, not a manual database change.
7. **Do not bypass the authoritative route** — if a WO's route looks wrong, fix it at
   release time through the proper WO Release screen, not by forcing a stage-skip.
8. **Do not change historical transaction quantities** — production, movement, packing,
   and dispatch records are immutable by design; a mistake is corrected with a new,
   clearly-labeled transaction, never by altering the old one.
