# OMS Change Control

The system is now in controlled operation against the baseline in
`docs/OMS_RELEASE_BASELINE.md`. No change is made directly from a feature request or an
observation — every change is classified first, then goes through the gate below.

## Change Classifications

| Class | Meaning | Example |
|---|---|---|
| A. Bug Fix | Existing behavior does not match the documented business rule | A route validation lets a stage be skipped |
| B. Security Fix | Authentication, authorization, secrets, or configuration weakness | A missing role check on a sensitive endpoint |
| C. Data Integrity Fix | Quantities, WIP, or ledgers can become incorrect or inconsistent | Dispatch crediting the wrong stage |
| D. Performance Fix | A real, evidenced slowdown affecting operations | A page or endpoint consistently timing out under normal load |
| E. Approved Feature Change | A genuinely new capability, requested and approved by the business | A new report, a new master-data type, a new workflow step |

A request that does not clearly fall into A–D is Class E by default, and Class E changes
are explicitly out of scope for engineering/stabilization sessions — they require a
separate, business-approved change request before any code is touched.

## Required Documentation Per Change

Every change, regardless of class, must record:

1. **Problem** — what is actually wrong or missing, in concrete terms
2. **Business impact** — who is affected and how, in production terms
3. **Requested change** — the specific, scoped fix or feature
4. **Affected module** — exact file(s)/service(s)/endpoint(s)
5. **Risk** — what could go wrong, including to unrelated functionality
6. **Test plan** — which existing tests cover it, and what new test proves the fix
7. **Approval** — who authorized the change (name/role, date)
8. **Implementation** — the actual diff/commit
9. **Verification** — test suite result, build result, and (for anything touching
   manufacturing logic) a live smoke-test result
10. **Release version** — the tag/commit the change ships in

## Engineering Change Gate (pre-implementation checklist)

Before writing any code for a proposed change, confirm all of the following are answered:

1. Problem statement
2. Business justification
3. Impact analysis (what breaks if this is wrong)
4. Existing behavior (with a file:line citation, not a guess)
5. Proposed behavior
6. Affected modules
7. Data impact (does it touch WIP/quantities/ledgers?)
8. Security impact (does it touch auth/RBAC/secrets?)
9. Regression test (existing or new)
10. UAT plan (how will this be verified against a real or rehearsal environment before go-live)
11. Rollback plan

If any of these cannot be answered, the change is not ready to implement — go back and
answer it first, per `docs/OMS_ENGINEERING_CHANGE_GATE` principles above (not a separate
file; enforced here).

## Rules

- Bug/Security/Data-Integrity/Performance fixes (Classes A–D) should be the **smallest
  possible change** that resolves the documented problem, with no unrelated refactoring.
- Feature changes (Class E) require explicit business approval before implementation and
  are never bundled into a stabilization or bug-fix pass.
- No change is made directly to production data or the production database to "fix" a
  transaction — see `docs/OMS_SUPPORT_RUNBOOK.md`.
- No change bypasses the existing OMS Engine, introduces a second business-rule engine,
  or builds Delivery Challan functionality inside OMS — these remain out of scope
  regardless of how a request is classified.

## Log

| Date | Class | Summary | Commit | Approved by |
|---|---|---|---|---|
| 2026-09-20 | A/C | Missing `Union` import crashing backend on non-3.14 Python; dispatch double-crediting multiple StageWIP rows | `a12123a` | UAT sign-off |
| 2026-09-20 | B | `/auth/register` unauthenticated (privilege escalation); wide-open CORS; hardcoded `SECRET_KEY` with no production guard | `a12123a` | UAT sign-off |
| 2026-09-20 | C | Idempotency not DB-enforced for movement/production; packing/dispatch had no idempotency or row locking | `a12123a` | UAT sign-off |
| 2026-09-20 | B/C | Seed routine reset real account passwords/roles on every restart; UUID→str serialization crash on `/register`, `/admin/customers`, `/admin/parts` | `f434c4d` | Go-live review |
| 2026-09-20 | C | BSR not actually enforced as a dispatch gate on routes where it is a distinct stage | `f93ec26` | Go-live rehearsal |

Add new rows here as future changes are approved and shipped — do not create a separate
changelog file.
