# OMS Escalation Matrix

Names/contacts are intentionally left as placeholders — fill in with actual VSPL personnel
before go-live. Do not invent names.

```
L1 — Operator / Department User
       (first point of contact for anything unexpected during a shift)
 ↓
L2 — Department / Production Manager
       (handles process questions, quantity disputes, approves corrections)
 ↓
L3 — OMS Application Admin
       (handles RBAC/account issues, audit-log review, master-data questions)
 ↓
L4 — Development / IT Support
       (handles suspected software defects, per docs/OMS_CHANGE_CONTROL.md)
 ↓
L5 — Database / Infrastructure Support
       (handles database connectivity, backup/restore, hosting/server issues)
```

## Contact Assignments

| Level | Name | Contact | Notes |
|---|---|---|---|
| L1 — Operator / Department User | ______________ | ______________ | Per shift/department |
| L2 — Department / Production Manager | ______________ | ______________ | |
| L3 — OMS Application Admin | ______________ | ______________ | Holds an `ADMIN` role account |
| L4 — Development / IT Support | ______________ | ______________ | |
| L5 — Database / Infrastructure Support | ______________ | ______________ | Owns backup/restore per `docs/OMS_BACKUP_RECOVERY.md` |

## When to Escalate to Which Level

- **L1 → L2**: a transaction was rejected and the operator doesn't understand why, or a
  quantity looks wrong and needs a supervisor decision.
- **L2 → L3**: the issue involves account access, role permissions, audit history, or
  needs an administrative action (e.g. reviewing who did what).
- **L3 → L4**: the behavior contradicts a documented business rule in
  `docs/OMS_BUSINESS_RULES.md` and cannot be explained by user/process error — a suspected
  genuine software defect. Classify severity per `docs/OMS_SUPPORT_RUNBOOK.md` (P0/P1
  require immediate escalation).
- **L4 → L5**: the application cannot reach the database, the database itself appears
  unhealthy, or a restore/backup action is needed.

Escalation always follows `docs/OMS_SUPPORT_RUNBOOK.md` for the specific diagnostic steps
per incident type, and `docs/OMS_CHANGE_CONTROL.md` before any code change is made.
