# OMS Master Data Governance

## Current State (as implemented)

| Master | Read | Write/Update/Delete |
|---|---|---|
| Customers | `GET /api/v1/admin/customers` (any authenticated user) | **No endpoint exists** — customers are only ever created implicitly during Order Intake if they don't already exist |
| Parts | `GET /api/v1/admin/parts` (any authenticated user) | **No endpoint exists** — same implicit-creation pattern via Order Intake |
| Machines | `GET /api/v1/admin/machines` (static, hardcoded list) | Not a database-backed master today |
| Operators | Represented as `User` records with a role | Managed via `POST /api/v1/auth/register`, **ADMIN-only** |
| Rejection reasons | Free-text `defect_code` on `NCRecord`, not a separate master table | N/A |
| Conversion factors | **Does not exist** — no unit-of-measure master in this system (only a WO-to-WO quantity-split feature, unrelated to unit conversion) | N/A |
| Routes/stages | Persisted per-WO in `WORoute` at release time, not a shared global master | Set via `POST /api/v1/operations/wo-release` |

## Rules

1. **Only authorized users modify protected masters.** Today the only actual "master"
   write surface is user/account creation, which already requires an ADMIN token
   (`POST /api/v1/auth/register`). There is no other master-data write endpoint in this
   system — so there is currently nothing else to lock down, but any future master-data
   write endpoint must include a role check from day one, not as a follow-up fix.
2. **Changes must be auditable.** User creation is not currently written to `AuditLog` in
   the way manufacturing mutations are — this is a **known gap**, not a defect
   (`AuditLog` was designed for manufacturing transactions). If user-account management
   needs an audit trail, that is a Class C/E change request, not an assumed existing
   capability.
3. **Historical transactions remain historically correct.** Since no conversion-factor
   master exists, there is nothing that could retroactively alter a historical
   transaction's meaning today. If a conversion-factor master is ever introduced (Class E),
   its design must store the factor used at transaction time on the transaction itself,
   never re-derive it from the current master value — matching the pattern already used by
   the existing WO-to-WO Conversion feature.
4. **Do not silently change historical records.** No master-data change should ever
   trigger a recalculation of past production, packing, or dispatch quantities.
5. **Do not create duplicate masters.** `Customer.customer_code` and `Part.part_number`
   are unique-constrained; Order Intake looks up by these before creating a new row.

## Operational Note

Because there is currently no dedicated master-data management UI or API beyond
read-only listings and implicit creation via Order Intake, any request for one (bulk
part import, customer management screen, rejection-reason master, conversion-factor
master, etc.) is a **Class E feature change** and must go through
`docs/OMS_CHANGE_CONTROL.md` — it is explicitly out of scope for stabilization/bug-fix work.
