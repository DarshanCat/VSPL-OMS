# OMS Weekly System Review

A recurring template — fill in one copy per week using real evidence (logs, DB queries,
audit records). Do not turn every observation into a development task; only genuine,
reproducible defects go to the engineering backlog under `docs/OMS_CHANGE_CONTROL.md`.

## Week of: ______

### Application Errors
- Count of 5xx responses / unhandled exceptions this week:
- Genuine defects vs. expected operational rejections (see
  `docs/OMS_SUPPORT_RUNBOOK.md` for how to tell them apart):

### Failed Transactions
- Production entry rejections (and whether each was a legitimate business rule or a bug):
- Movement rejections:
- Packing/Dispatch rejections:

### Duplicate Transaction Attempts
- Any `client_request_id` reused across genuinely different transactions:
- Any ledger table found with more than one row for the same idempotency key (should
  never happen — a P0 if found):

### WIP / Production / Rejection / Packing / Dispatch Discrepancies
- Any WO where `is_balanced: false` from the reconciliation endpoint, and root cause
  (data issue / process issue / existing business rule / genuine defect):
- Any negative quantity found anywhere (should never happen — a P0 if found):

### RBAC Failures
- Any 403s that indicate a legitimate role trying to do legitimate work (a real gap,
  worth a change request) vs. an unauthorized attempt (working as intended):

### Database Health
- Connectivity issues this week:
- Any manual intervention performed (should be none per
  `docs/OMS_SUPPORT_RUNBOOK.md` — flag immediately if it happened):

### Backup Health
- Backups completed this week / expected count:
- Last verified restorable backup:

### Performance Observations
- Any endpoint/page with a materially worse response time than baseline, with evidence
  (not a guess):

## Classification Summary

| Finding | P0/P1/P2/P3 | Root Cause | Action |
|---|---|---|---|
| | | | |

Only P0/P1 rows require immediate engineering intervention under
`docs/OMS_CHANGE_CONTROL.md`. P2/P3 rows are logged for awareness, not automatically
converted into feature work.
