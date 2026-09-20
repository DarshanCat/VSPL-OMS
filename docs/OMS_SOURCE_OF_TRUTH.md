# OMS Source-of-Truth Matrix

| Domain | Authoritative System |
|---|---|
| OAR / Order Intake | OMS (`Order`, `OperationsService.create_order_intake`) |
| Work Order | OMS (`WorkOrder`) |
| WO Route | OMS (`WORoute`, per-WO, dynamic) |
| Production (OK/Reject entries) | OMS (`ProductionUpdate`) |
| Stage WIP | OMS (`StageWIP`, derived by `OMSIntegrationService.recompute_work_order`) |
| Movement between stages | OMS (`ProductionMovement`) |
| Quality / Rejection (NC) | OMS (`NCRecord`) |
| Packing | OMS (`PackingRecord`, `PackingTransaction`) |
| Dispatch (manufacturing state: quantity, terminal stage) | OMS (`Dispatch`, `StageWIP` terminal row) |
| Delivery Challan / vendor DC process | **External DC software** — not implemented in, and must never be implemented inside, OMS |
| User identity / authentication | OMS's own `User` table + JWT (`app/core/security.py`) — this system does not integrate with an external identity provider today; if one is introduced later, that is a Class E change |
| Audit trail | OMS (`AuditLog`) |
| Mathematical KPIs (yield %, achievement %, OEE proxy, etc.) | OMS-derived (`app/analytics/math_engine.py`) — deterministic functions over OMS data, not a separate source of truth |
| ML predictions (delay risk, rejection risk, bottleneck, forecast, anomaly) | Derived/advisory only (`app/analytics/ml_models.py`) — never authoritative for any actual quantity; see `docs/OMS_AI_ML_GOVERNANCE.md` |
| AI Copilot answers | Derived/advisory only (`app/services/ai_service.py`) — reads OMS data to answer questions, never writes manufacturing facts |

## Rules for this matrix

- Only systems that actually exist in this repository are listed as authoritative. DC
  software is explicitly **external** and out of scope — OMS must never claim or gain
  ownership of DC creation, vendor DC workflow, security gate workflow, store inward
  workflow, payment approval, or DC closure.
- If OMS is ever integrated with a real external identity provider (SSO/LDAP/etc.), update
  the "User identity" row through the change-control process — do not silently assume one
  exists.
- Analytics and ML are always *derived from* OMS data, never a parallel or competing
  source of truth for any manufacturing quantity.
