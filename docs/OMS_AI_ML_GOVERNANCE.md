# OMS AI / ML Governance

## The separation (as actually implemented)

| Layer | Role | Where | Can it write manufacturing data? |
|---|---|---|---|
| **Deterministic OMS Engine** | Actual manufacturing truth — routes, targets, RAG status, reconciliation | `app/oms_core/oms_engine.py`, `app/services/oms_integration_service.py` | Yes — this is the only layer that ever writes `StageWIP`/`WORoute`/quantities, via the normal production/movement/packing/dispatch services |
| **Mathematical Analytics** | Deterministic KPIs computed *from* OMS data | `app/analytics/math_engine.py` (Achievement %, Yield %, Rejection Rate, Velocity, Takt Time, OEE proxy, etc.) | **No** — pure functions, no database writes |
| **ML** | Prediction / forecasting / anomaly detection | `app/analytics/ml_models.py` (`DelayPredictionModel`, `RejectionRiskModel`, `BottleneckPredictionModel`, `ProductionForecastingModel`, `AnomalyDetectionModel`) with `ModelGovernance` | **No** — verified by code inspection: no `db.add`/`db.commit`/`.update()` call exists anywhere in `app/analytics/` |
| **AI Copilot** | Explanation / recommendation over OMS data | `app/services/ai_service.py` (`answer_query`, `get_proactive_insights`) | **No** — verified by code inspection: no database write call exists in this file |

## Hard rule

AI/ML must never overwrite, and today does not overwrite:
- Target quantity
- Production quantity
- Rejection
- WIP
- Movement
- Packing
- Dispatch
- Historical transactions

Every one of these is written exclusively through the deterministic service layer
(`ProductionService`, `PackingService`, `DispatchService`, `OperationsService`), which the
analytics/ML/AI layers only ever *read from*.

## Insufficient data

`ModelGovernance` in `app/analytics/ml_models.py` explicitly returns a status of
`INSUFFICIENT_DATA` (alongside `TRAINED`/`BASELINE_STATISTICAL`) when there isn't enough
history to produce a reliable prediction, rather than fabricating a number. This behavior
is already implemented and must be preserved in any future change to the analytics layer.

## Change control implication

Any request to have an AI/ML feature *act* on manufacturing data (auto-adjust a target,
auto-approve a dispatch, auto-close an NC, etc.) is a fundamental violation of this
governance model, not a normal feature request — it must be explicitly rejected or escalated
for a business/architecture decision, never implemented as an incremental change.
