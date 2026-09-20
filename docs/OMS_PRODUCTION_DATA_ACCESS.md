# OMS Production Data Access Policy

Backend RBAC (`require_roles` / `get_current_user` in `backend/app/api/deps.py`) is
authoritative. The frontend never determines access on its own — hiding a button is a
convenience, not a control.

## Roles that exist
`ADMIN`, `CEO`, `PRODUCTION_MANAGER`, `PLANNER`, `QA`, `DISPATCH`, `MACHINE_OPERATOR`,
`OPERATOR`, `PACKING`, `STORE`, `SALES` (`backend/app/models/user.py`).

## What is actually enforced today

| Action | Enforcement |
|---|---|
| View production/WIP/dashboard/reports data | Any authenticated user |
| Create production entry / movement | Any authenticated user (no role restriction) |
| Packing update | Any authenticated user (no role restriction) |
| Dispatch | Any authenticated user (no role restriction) |
| Order intake / WO release / conversion / NC create-update | Any authenticated user (no role restriction) |
| View audit logs | `ADMIN`, `PRODUCTION_MANAGER`, `QA`, `CEO` only |
| Create a new user account (`/auth/register`) | `ADMIN` only |
| Run OMS daily-cycle / download master or report files | `ADMIN`, `PLANNER`, `PRODUCTION_MANAGER` only |
| Edit/delete a posted production, movement, packing, dispatch, or audit record | **No endpoint exists for this at all** — immutable by construction, not by a role check |

## Honest statement of the gap

There is currently **no business-approved role matrix** restricting who may perform
production entry, movement, packing, dispatch, order intake, WO release, conversion, or NC
actions beyond "must be a logged-in user." This is a known, documented limitation (see
`docs/OMS_RELEASE_BASELINE.md`), not something this document should paper over. Closing it
requires the business to define the intended matrix (e.g. "only OPERATOR/MACHINE_OPERATOR
may post production entries," "only DISPATCH may execute dispatch," "only QA may create/
update NC records") — that is a Class E-adjacent change (it changes who can do what, so it
needs business sign-off) implemented as a Class B (security/access) fix once the matrix is
approved.

## Who can view production data
Any authenticated user, across all roles. There is no per-plant or per-customer data
partitioning in this system.

## Who can create transactions
Any authenticated user, across all roles (see gap above).

## Who can approve/review
No formal "approval" workflow exists beyond NC status transitions
(`PUT /api/v1/operations/nc`), which — like the other action endpoints — currently accepts
any authenticated user.

## Who can manage masters
No one, via the API — no master-data write endpoint exists except user-account creation
(ADMIN only). See `docs/OMS_MASTER_DATA_GOVERNANCE.md`.

## Who can access audit information
`ADMIN`, `PRODUCTION_MANAGER`, `QA`, `CEO`.

## Who can administer the application
`ADMIN` (user creation) and `ADMIN`/`PLANNER`/`PRODUCTION_MANAGER` (OMS cycle run/downloads).
There is no separate "application administration" surface beyond this.
