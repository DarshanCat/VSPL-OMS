from typing import Optional, List
from pydantic import BaseModel

class RejectionByStageStat(BaseModel):
    stage: str
    total_ok: int
    total_rejected: int
    reject_pct: float

class TopDefectStat(BaseModel):
    defect_code: str
    rejected_qty: int
    pct_of_total: float

class DelayedOrderStat(BaseModel):
    wo_number: str
    customer_code: str
    customer_name: str
    part_number: str
    current_stage: str
    order_qty: int
    delivery_date: Optional[str] = None
    days_overdue: int
    delivery_risk: str

class BottleneckStat(BaseModel):
    stage: str
    wip_count: int
    wo_count: int
    avg_dwell_hours: float
    status: str  # Normal, Busy, Critical

class ProductionTrendStat(BaseModel):
    date: str
    good_produced: int
    rejected_qty: int
    dispatched_qty: int

class MachineUtilizationStat(BaseModel):
    machine_id: str
    status: str  # Running, Idle, Maintenance
    current_wo: Optional[str] = None
    utilization_pct: float
    output_today: int

class DashboardStatsOut(BaseModel):
    today_date: str
    total_orders_today: int
    open_orders_count: int
    completed_orders_count: int
    delayed_orders_count: int
    running_work_orders: int
    pending_work_orders: int
    current_total_wip: int
    total_rejected_qty: int
    overall_yield_pct: float
    packing_pending_qty: int
    dispatch_pending_qty: int
    open_ncs_count: int
    rejection_by_stage: List[RejectionByStageStat]
    top_defects: List[TopDefectStat]
    top_delayed_orders: List[DelayedOrderStat]
    bottlenecks: List[BottleneckStat]
    production_trend: List[ProductionTrendStat]
    machine_utilization: List[MachineUtilizationStat]
