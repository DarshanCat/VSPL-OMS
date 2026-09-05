from typing import Optional, List
from datetime import datetime, date
from pydantic import BaseModel, ConfigDict

class WORouteItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stage: str
    sequence: int
    stage_target_qty: int
    cumulative_ok_qty: int
    cumulative_rej_qty: int
    cumulative_inproc_qty: int
    cumulative_onhand_qty: int
    stage_status: str

class WorkOrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    wo_number: str
    oar_number: Optional[str] = None
    customer_code: str
    customer_name: str
    part_number: str
    part_name: Optional[str] = None
    grade: Optional[str] = None
    order_qty: int
    physical_wo_qty: int
    current_stage: str
    next_allowed_stage: Optional[str] = None
    available_wip_at_current_stage: int
    status: str
    delivery_risk: str
    shortfall: str
    delivery_date: Optional[date] = None
    created_at: datetime

class StageTimelineStep(BaseModel):
    stage: str
    sequence: int
    name: str
    is_current: bool
    is_completed: bool
    is_pending: bool
    is_skip: bool
    rag_status: str
    target_qty: int
    ok_completed_qty: int
    in_process_qty: int
    on_hand_wip: int
    rejected_qty: int
    last_movement_at: Optional[datetime] = None
    machine: Optional[str] = None
    operator: Optional[str] = None
    duration_hours: Optional[float] = None

class WorkOrderTrackingDetail(BaseModel):
    id: str
    wo_number: str
    oar_number: Optional[str] = None
    customer_code: str
    customer_name: str
    customer_po: str
    part_number: str
    part_name: Optional[str] = None
    grade: Optional[str] = None
    order_qty: int
    physical_wo_qty: int
    current_stage: str
    next_allowed_stage: Optional[str] = None
    available_wip: int
    status: str
    shortfall: str
    projected_final_good: int
    delivery_risk: str
    delivery_date: Optional[date] = None
    route_string: str
    timeline: List[StageTimelineStep]
    total_wip_on_hand: int
    total_rejected: int
    yield_pct: float
    created_at: datetime
