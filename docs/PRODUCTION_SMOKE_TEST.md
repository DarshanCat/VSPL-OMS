# OMS Production Smoke Test

Run this checklist immediately after every production deployment, using a dedicated
test/UAT Work Order where possible — never fabricate quantities against a real customer
WO. Each check should be done through the real UI hitting the real API, not just a page load.

## 1. Health & Startup
- [ ] `GET /health` on the backend returns `200 {"status": "online", ...}`
- [ ] Backend logs show no startup errors (no `RuntimeError` from the `SECRET_KEY` guard,
      no DB connection failure)
- [ ] Frontend loads at the production URL with no console errors

## 2. Authentication & RBAC
- [ ] Login with a seeded/real account succeeds and returns a working session
- [ ] Login with a wrong password is rejected (401)
- [ ] `POST /api/v1/auth/register` without an ADMIN token is rejected (401/403) — confirms
      the self-registration privilege-escalation hole stays closed
- [ ] `GET /api/v1/admin/audit-logs` without a management-role token is rejected (403)

## 3. Core OMS Flow (use an isolated UAT WO)
- [ ] **OAR / Order Intake**: create an order intake, confirm a Work Order is generated
- [ ] **WO Release**: release the WO with its route, confirm route stages and targets appear
- [ ] **Production Entry**: post a fresh OK/Reject quantity — confirm the input field starts
      blank (not pre-filled with available WIP) and the stage total updates correctly
- [ ] **Movement**: move a partial quantity to the next stage only — confirm skipping a
      stage or moving to a different WO is rejected
- [ ] **Quality/Rejection**: post a rejection, confirm an NC record is created and the
      rejected quantity does not appear as good downstream
- [ ] **Packing**: post a partial packing quantity, confirm `pending_qty` decreases and
      `ready_for_dispatch_qty` increases correctly
- [ ] **BSR**: only exercise this if the WO's route actually includes a BSR stage; confirm
      it is not required when the route omits it
- [ ] **Dispatch**: dispatch a partial quantity, confirm over-dispatch beyond
      `ready_for_dispatch_qty` is rejected, and that only the WO's terminal stage
      (not every PACKING/BSR-aliased stage) shows the dispatched quantity
- [ ] **Analytics/Dashboard**: confirm plant KPIs reflect the test WO's activity

## 4. Data Integrity
- [ ] **Idempotency**: resubmit the exact same production/movement/packing/dispatch
      request with the same `client_request_id` — confirm only one transaction is recorded
      and the response indicates a duplicate
- [ ] **Audit**: confirm an audit log entry exists for each action performed above
      (visible via `GET /api/v1/admin/audit-logs` as an ADMIN/PRODUCTION_MANAGER/QA/CEO user)
- [ ] **Reconciliation**: `Released Qty = Total WIP + Total Rejected + Dispatched Qty` holds
      for the test WO (via the reconciliation endpoint/report)

## 5. Configuration Sanity
- [ ] Frontend is calling the production API URL, not `localhost`
- [ ] Browser dev tools show CORS allowing only the production frontend origin (not `*`)
- [ ] No stack trace or internal error detail is returned to the browser on a forced error
      (e.g. an invalid request) — only a generic error message

## 6. Sign-off
Record: date/time, tester, environment, WO number(s) used for testing, and pass/fail per
section above. Any failure here blocks go-live until resolved.
