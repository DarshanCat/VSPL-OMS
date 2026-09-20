# VSPL OMS — BUSINESS HANDOVER

## 1. System Status

- **Engineering:** COMPLETE
- **UAT:** COMPLETE (rehearsal verified)
- **Production rehearsal:** COMPLETE
- **Governance:** COMPLETE
- **Production readiness:** VERIFIED BY REHEARSAL

**REAL PRODUCTION TELEMETRY HAS NOT BEEN VERIFIED FROM THIS ENVIRONMENT.** Every check
performed to date — functional, security, data-integrity, and stabilization — was run
against a fresh, isolated rehearsal instance built from the exact release commit, because
this environment has no connection to VSPL's actual production servers, database, or
users. Do not treat any statement in this document or its companion governance documents
as evidence of real production uptime, real user activity, or real backup success. Those
must be established on the actual production infrastructure per
`docs/PRODUCTION_DEPLOYMENT.md` and `docs/PRODUCTION_SMOKE_TEST.md`, and recorded going
forward using `docs/OMS_DAILY_OPERATIONS_CHECKLIST.md` and `docs/OMS_WEEKLY_REVIEW.md`.

## 2. What OMS Owns

OMS is the authoritative system for manufacturing execution information, specifically:

- OAR (Order Acknowledgement Record) / Order Intake
- Work Orders
- WO Routes (dynamic, per Work Order)
- Production (stage-level OK/Reject entries)
- Stage WIP
- Movement (stage-to-stage transfer of physical material)
- Quality / Rejection (NC records)
- Packing
- BSR, where a Work Order's route includes it
- Dispatch manufacturing state (quantity, terminal stage, dispatch history)
- Manufacturing analytics derived from the above (KPIs, reconciliation, ML-based
  predictions and anomaly signals — always advisory, never authoritative; see
  `docs/OMS_AI_ML_GOVERNANCE.md`)

See `docs/OMS_SOURCE_OF_TRUTH.md` for the full domain-by-domain matrix.

## 3. What OMS Does NOT Own

**Delivery Challan (DC) workflow remains entirely in VSPL's separate DC application.**
OMS does not own, and must never be extended to own:

- DC creation
- Vendor DC workflow
- Security gate DC workflow
- Store inward DC workflow
- Payment workflow
- DC closure

Any request to bring DC functionality inside OMS is out of scope and must not be
implemented — it would require a separate, explicitly approved architectural decision, not
an incremental change under `docs/OMS_CHANGE_CONTROL.md`.

## 4. Operator Workflow

```
OAR
 ↓
WORK ORDER
 ↓
ROUTE
 ↓
PRODUCTION
 ↓
MOVEMENT
 ↓
QUALITY
 ↓
WIP
 ↓
PACKING
 ↓
BSR (where applicable)
 ↓
DISPATCH
 ↓
ANALYTICS
```

The actual sequence of stages (which of F1/F2/F3/SP/FI/PACKING/BSR/etc. apply, and in what
order) is determined **per individual Work Order** at release time — there is no single
fixed route for every WO. Some WOs include BSR, some do not; operators always follow the
route shown for the specific WO they are working on, never a general assumption.

## 5. Critical Operator Rules

1. **Every production entry is a NEW transaction quantity.**
2. **Do not enter the cumulative completed quantity as the new transaction** — enter only
   what was actually just completed.
3. **Production and movement are separate events** — completing production at a stage does
   not automatically move material to the next stage; that is a distinct transaction.
4. **Rejected quantity does not move forward as good quantity.**
5. **Never move material between Work Orders.**
6. **Never bypass the WO route** — you cannot skip a stage or use a different order than
   the one shown for that WO.
7. **Never manually modify database quantities.**
8. **Never delete manufacturing transactions.**
9. **If a transaction is wrong, use the approved correction/reconciliation process** (see
   `docs/OMS_SUPPORT_RUNBOOK.md` Case 3) — never edit or delete history.
10. **If unsure, stop the transaction and contact the designated OMS administrator** rather
    than guessing.

## 6. Role Handover

Roles that exist in the system today: `ADMIN`, `CEO`, `PRODUCTION_MANAGER`, `PLANNER`,
`QA`, `DISPATCH`, `MACHINE_OPERATOR`, `OPERATOR`, `PACKING`, `STORE`, `SALES`.

What is actually enforced by the backend today (verified, not assumed):

- **Operator** (`MACHINE_OPERATOR`/`OPERATOR`): can perform production entry, movement,
  packing, dispatch, order intake, WO release, conversion, and NC actions — the same as
  every other authenticated role, because these endpoints currently require only a valid
  login, not a specific role. Operators **cannot** view audit logs, register new accounts,
  or run the OMS daily-cycle/download functions.
- **QA**: can perform the same production-floor actions as any authenticated user, and can
  additionally view audit logs.
- **Production Manager**: can perform the same production-floor actions as any
  authenticated user, can view audit logs, and can run the OMS daily-cycle/download
  functions.
- **Admin**: can do everything above, plus create new user accounts
  (`POST /api/v1/auth/register`).

**Business permission matrix requires formal business-owner confirmation.** The current
implementation does not restrict floor-execution actions (production entry, movement,
packing, dispatch) to specific roles — any authenticated user can perform any of them. If
VSPL's business owners want, for example, only Dispatch staff to execute dispatch, or only
QA to disposition NC records, that matrix must be formally defined and approved, then
implemented as a classified change under `docs/OMS_CHANGE_CONTROL.md`. This is not solved
by a code change made during this handover phase.

## 7. Known Operational Limitations

1. Real production telemetry (uptime, real user activity, real transaction volume) has not
   been observed from this environment — only rehearsal verification exists.
2. Automated backup scheduling is infrastructure-dependent and has not been configured or
   verified in this repository; it must be set up and verified on VSPL's actual production
   infrastructure (managed PostgreSQL backups, or a scheduled `pg_dump`) — see
   `docs/OMS_BACKUP_RECOVERY.md`.
3. The fine-grained business RBAC matrix (which specific role may perform which
   floor-execution action) requires formal business-owner confirmation; it is not yet
   approved or implemented beyond "must be an authenticated user."

These are documented limitations, not software defects — no evidence exists that any of
them causes incorrect manufacturing data; they are gaps in operational configuration and
business decision-making, respectively.

## 8. Production Go-Live Checklist

### Infrastructure
- [ ] Production server available
- [ ] PostgreSQL production database available
- [ ] Production environment variables configured (`DATABASE_URL`, `SECRET_KEY`,
      `ENVIRONMENT=production`, `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`)
- [ ] Secrets configured securely (via environment/secret manager, never hardcoded)
- [ ] Production URL configured
- [ ] TLS/HTTPS configured (via your reverse proxy — not provided by this application)
- [ ] Backup configured
- [ ] Backup restore procedure verified with an actual test restore

### Application
- [ ] Correct release deployed (`oms-v1.0.0`, commit `4837c934bca71594eae207d65ccbcd4b8d5ca1b2`)
- [ ] Backend healthy
- [ ] Frontend healthy
- [ ] Health endpoint returns 200
- [ ] Authentication verified
- [ ] RBAC verified (per the actual matrix documented in §6, not an assumed one)
- [ ] Database migration verified (schema matches `docs/OMS_RELEASE_BASELINE.md`)

### Business
- [ ] Business users trained
- [ ] Operator workflow explained
- [ ] QA workflow explained
- [ ] Manager workflow explained
- [ ] Admin workflow explained
- [ ] Master-data ownership assigned (who handles new customers/parts via Order Intake)
- [ ] Reconciliation responsibility assigned (who runs/reviews
      `docs/OMS_DAILY_OPERATIONS_CHECKLIST.md` end-of-day reconciliation)

### Operations
- [ ] Daily checklist assigned (`docs/OMS_DAILY_OPERATIONS_CHECKLIST.md`)
- [ ] Weekly review owner assigned (`docs/OMS_WEEKLY_REVIEW.md`)
- [ ] Support contact assigned (see `docs/OMS_ESCALATION_MATRIX.md`)
- [ ] Incident escalation defined (`docs/OMS_ESCALATION_MATRIX.md`,
      `docs/OMS_SUPPORT_RUNBOOK.md`)
- [ ] Backup owner assigned

## 9. First-Day Operations

### Start of Shift
- [ ] Login works
- [ ] Dashboard works
- [ ] Active WOs visible
- [ ] Routes correct for each active WO
- [ ] Production entry available
- [ ] Existing WIP visible and matches expectation

### During Shift
- [ ] Production entries recorded (fresh deltas, not cumulative totals — see Rule 1/2)
- [ ] Movements recorded
- [ ] Quality recorded
- [ ] Packing recorded
- [ ] BSR recorded where applicable
- [ ] Dispatch recorded
- [ ] Errors reported through the support process (`docs/OMS_SUPPORT_RUNBOOK.md`), not
      worked around

### End of Shift
- [ ] Production reviewed
- [ ] Rejections reviewed
- [ ] WIP reconciled (`is_plant_balanced: true` via the reconciliation endpoint)
- [ ] Packing reviewed
- [ ] Dispatch reviewed
- [ ] Exceptions escalated per `docs/OMS_ESCALATION_MATRIX.md`
