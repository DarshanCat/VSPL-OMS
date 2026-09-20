# OMS Production Data Access Policy

Backend RBAC (`require_roles` / `get_current_user` in `backend/app/api/deps.py`) is
authoritative. The frontend never determines access on its own — hiding a button is a
convenience, not a control.

## Roles that exist
`ADMIN`, `CEO`, `PRODUCTION_MANAGER`, `PLANNER`, `QA`, `DISPATCH`, `MACHINE_OPERATOR`,
`OPERATOR`, `PACKING`, `STORE`, `SALES` (`backend/app/models/user.py`).

## What is actually enforced today

Updated after the security-hardening RBAC remediation (see `docs/OMS_CHANGE_CONTROL.md`
log for the exact commits). Each gate below reuses an existing role grouping already used
elsewhere in the codebase — no new permission concept was invented.

| Action | Enforcement |
|---|---|
| View production/WIP/dashboard/reports data | Any authenticated user |
| Create production entry / movement | Any authenticated user (no role restriction — open by design pending a business decision) |
| Packing update | Any authenticated user (no role restriction — open by design pending a business decision) |
| Order intake | Any authenticated user (no role restriction — open by design pending a business decision) |
| NC creation (report a defect) | Any authenticated user — deliberately open; this is normal shop-floor reporting |
| **WO release** | `ADMIN`, `PLANNER`, `PRODUCTION_MANAGER` only |
| **Conversion** | `ADMIN`, `PLANNER`, `PRODUCTION_MANAGER` only |
| **Dispatch (`POST /dispatch/ship`)** | `DISPATCH`, `PRODUCTION_MANAGER`, `ADMIN` only |
| **NC disposition (`PUT /operations/nc`)** | `ADMIN`, `PRODUCTION_MANAGER`, `QA`, `CEO` only |
| View audit logs | `ADMIN`, `PRODUCTION_MANAGER`, `QA`, `CEO` only |
| Create a new user account (`/auth/register`) | `ADMIN` only |
| Run OMS daily-cycle / download master or report files | `ADMIN`, `PLANNER`, `PRODUCTION_MANAGER` only |
| Edit/delete a posted production, movement, packing, dispatch, or audit record | **No endpoint exists for this at all** — immutable by construction, not by a role check |

## Honest statement of the remaining gap

Production entry, movement, packing, and order intake still accept any authenticated
user — this is a known, deliberate scope limit, not an oversight. Closing it further
(e.g. "only OPERATOR/MACHINE_OPERATOR may post production entries," "only PACKING may post
packing transactions") requires the business to define the intended matrix first — that is
a Class E-adjacent change (it changes who can do what, so it needs business sign-off)
implemented as a Class B (security/access) fix once approved. The four highest-risk gaps
(release, conversion, dispatch, NC disposition) have already been closed and
regression-tested (`backend/tests/test_rbac_remediation.py`).

## Who can view production data
Any authenticated user, across all roles. There is no per-plant or per-customer data
partitioning in this system.

## Who can create transactions
Production entry, movement, packing, order intake, and NC creation: any authenticated
user (see gap above). WO release, conversion, and dispatch: restricted per the table above.

## Who can approve/review
NC disposition (`PUT /api/v1/operations/nc`) is restricted to `ADMIN`, `PRODUCTION_MANAGER`,
`QA`, `CEO`. No other formal "approval" workflow exists in this system.

## Who can manage masters
No one, via the API — no master-data write endpoint exists except user-account creation
(ADMIN only). See `docs/OMS_MASTER_DATA_GOVERNANCE.md`.

## Who can access audit information
`ADMIN`, `PRODUCTION_MANAGER`, `QA`, `CEO`.

## Who can administer the application
`ADMIN` (user creation) and `ADMIN`/`PLANNER`/`PRODUCTION_MANAGER` (OMS cycle run/downloads).
There is no separate "application administration" surface beyond this.
