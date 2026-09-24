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
    match_size: Optional[int] = None
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

class TransactionHistoryItem(BaseModel):
    id: str
    timestamp: datetime
    transaction_type: str
    stage: str
    to_stage: Optional[str] = None
    quantity: int
    rejected_qty: int = 0
    defect_code: Optional[str] = None
    machine_id: Optional[str] = None
    operator_name: Optional[str] = None
    shift: Optional[str] = None
    remarks: Optional[str] = None
    client_request_id: Optional[str] = None

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
    match_size: Optional[int] = None
    current_stage: str
    next_allowed_stage: Optional[str] = None
    available_wip: int
    # The stage the Move Parts screen must actually use for a new movement. `current_stage`
    # is the OMS "furthest stage touched" snapshot (used for dashboards/RAG/reporting) --
    # it advances to the next stage as soon as ANY quantity has been moved into it, even
    # while the prior stage still has movable WIP sitting available. Movement eligibility
    # is a different question: it's the earliest stage (by route sequence) that still has
    # available_wip > 0. Both are derived from the same authoritative StageWIP.available_wip
    # values already computed above; this is not a new quantity engine, just picking the
    # correct one of two existing, legitimate readings for the movement use case.
    movable_from_stage: Optional[str] = None
    movable_to_stage: Optional[str] = None
    movable_wip: int = 0
    status: str
    shortfall: str
    projected_final_good: int
    delivery_risk: str
    delivery_date: Optional[date] = None
    route_string: str
    timeline: List[StageTimelineStep]
    transactions: List[TransactionHistoryItem] = []
    total_wip_on_hand: int
    total_rejected: int
    yield_pct: float
    created_at: datetime

class OARWorkOrderSummary(BaseModel):
    wo_number: str
    allocated_qty: int
    release_status: str
    current_stage: str
    wo_status: str
    ok_completed: int
    rejected: int
    movable_wip: int
    dispatched_qty: int

class OARListItem(BaseModel):
    oar_number: str
    order_id: str
    customer_code: str
    customer_name: str
    customer_po: str
    part_number: str
    oar_qty: int
    allocated_qty: int
    remaining_qty: int
    num_wos: int
    status: str
    delivery_date: Optional[date] = None
    created_at: datetime
    work_orders: List[OARWorkOrderSummary]

class WorkOrderRouteResponse(BaseModel):
    wo_number: str
    physical_wo_qty: int
    match_size: Optional[int] = None
    current_stage: str
    route_stages: List[str]
    next_stage: Optional[str] = None
    stage_targets: dict
