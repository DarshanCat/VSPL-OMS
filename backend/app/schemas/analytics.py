"""
VSPL SMES + OMS - Analytics Schemas
Pydantic contracts for Mathematical KPIs, ML Predictions, Forecasts, and Governance.
"""

from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field


class PlantKPIsResponse(BaseModel):
    overall_achievement_pct: float
    overall_yield_pct: float
    plant_rejection_rate_pct: float
    total_plant_wip: int
    production_velocity_units_hr: float
    oee_proxy_pct: float
    total_open_work_orders: int
    total_dispatched_units: int
    generated_at: str


class StageKPIItem(BaseModel):
    stage: str
    target_qty: int
    ok_completed_qty: int
    rejection_qty: int
    in_process_wip: int
    available_wip: int
    rejection_rate_pct: float
    stage_completion_pct: float
    live_status: str


class WOKPIResponse(BaseModel):
    wo_number: str
    part_number: str
    part_grade: str
    physical_wo_qty: int
    current_stage: str
    overall_yield_pct: float
    total_scrap_qty: int
    route_stages: List[str]
    stage_metrics: List[StageKPIItem]
    generated_at: str


class DelayPredictionRequest(BaseModel):
    wo_number: str


class DelayPredictionResponse(BaseModel):
    wo_number: str
    governance: Dict[str, Any]
    current_stage: str
    delay_probability_pct: Optional[float] = None
    expected_completion_date: Optional[str] = None
    estimated_production_hours: Optional[float] = None
    days_to_deadline: Optional[int] = None
    risk_level: str
    recommendation: Optional[str] = None
    reason: Optional[str] = None


class RejectionRiskRequest(BaseModel):
    wo_number: str
    target_stage: Optional[str] = None
    machine_id: Optional[str] = None
    quantity: Optional[int] = None


class RejectionRiskResponse(BaseModel):
    wo_number: str
    governance: Dict[str, Any]
    stage: str
    predicted_rejection_rate_pct: Optional[float] = None
    expected_rejection_qty: Optional[int] = None
    probable_defect_code: Optional[str] = None
    risk_level: str
    recommendation: Optional[str] = None
    reason: Optional[str] = None


class StageBottleneckItem(BaseModel):
    stage: str
    current_wip: int
    wip_share_pct: float
    bottleneck_risk: str
    contributing_factors: List[str]
    recommended_action: str


class BottleneckAnalysisResponse(BaseModel):
    governance: Dict[str, Any]
    primary_bottleneck_stage: str
    total_plant_wip: int
    stage_breakdown: List[StageBottleneckItem]


class ForecastDayItem(BaseModel):
    day_index: int
    date: str
    predicted_daily_output: float
    cumulative_forecast: float
    lower_bound_95: float
    upper_bound_95: float


class ProductionForecastResponse(BaseModel):
    governance: Dict[str, Any]
    trend_direction: str
    projected_daily_mean: Optional[float] = None
    projected_weekly_output: Optional[float] = None
    forecast_points: List[ForecastDayItem] = []
    reason: Optional[str] = None


class AnomalyAlertItem(BaseModel):
    anomaly_type: str
    severity: str
    impacted_entity: str
    observed_value: str
    expected_baseline: str
    diagnosis: str
    recommended_action: str


class AnomalyScanResponse(BaseModel):
    governance: Dict[str, Any]
    total_anomalies_detected: int
    anomaly_alerts: List[AnomalyAlertItem]


class ModelRegistryItem(BaseModel):
    model_name: str
    version: str
    type: str
    status: str
    sample_count: int
    min_samples_required: int
    accuracy_benchmark: str
    last_evaluated: str


class ModelGovernanceResponse(BaseModel):
    registry_version: str
    data_pipeline_metadata: Dict[str, Any]
    registered_models: List[ModelRegistryItem]
    feedback_records_count: int


class PredictionFeedbackRequest(BaseModel):
    wo_number: str
    model_name: str
    predicted_outcome: Any
    actual_outcome: Any
    notes: Optional[str] = None
