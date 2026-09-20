# OMS Release Card

| Field | Value |
|---|---|
| OMS | VSPL Manufacturing OMS |
| Release | `oms-v1.0.0` |
| Application Commit | `3cb9c41beb9904a61b020d922d9fd96579bc7b86` |
| Governance Commit | `3a6e9d6` (governance docs) + 3 subsequent security-hardening commits (`076c530`, `76b9124`, `3cb9c41`) |
| Backend Tests | 122/122 PASS, 2 skipped (SQLite-only concurrency tests; verified passing against real PostgreSQL) |
| Security Tests | 74/74 PASS |
| Red Team | PASSED WITH ACCEPTED RESIDUAL RISK |
| TypeScript | PASS |
| Production Build | PASS |
| npm audit | 0 vulnerabilities |
| pip-audit | 1 accepted residual (`ecdsa`, confirmed unreachable) |
| Engineering Status | COMPLETE |
| Governance Status | OPERATIONALLY CONTROLLED |
| Real Production Verification | PENDING ACTUAL INFRASTRUCTURE ACCESS |
| Feature Development | FROZEN |
| Future Changes | CONTROLLED CHANGE REQUEST ONLY (`docs/OMS_CHANGE_CONTROL.md`) |
