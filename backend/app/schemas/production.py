from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class MovePartsRequest(BaseModel):
    wo_number: str = Field(..., description="Work Order Number e.g. WO-1001")
    from_stage: str = Field(..., description="Current stage e.g. F1, F2, F3, SP, FI, PACKING, BSR")
    to_stage: str = Field(..., description="Target stage e.g. F2, F3, SP, FI, PACKING, DISPATCH")
    quantity_moved: int = Field(..., gt=0, description="Quantity of good parts to move to next stage")
    rejected_quantity: int = Field(0, ge=0, description="Quantity of rejected parts at current stage")
    machine_id: Optional[str] = None
    operator_id: Optional[str] = None
    operator_name: Optional[str] = None
    shift: Optional[str] = "Shift A"
    defect_code: Optional[str] = None
    remarks: Optional[str] = None
    client_request_id: Optional[str] = Field(None, description="Unique client idempotency token to prevent double submissions")
    source_type: Optional[str] = Field("SMES_UI", description="Source: SMES_UI | EXCEL_IMPORT | API | SYSTEM")

class MovementResponse(BaseModel):
    success: bool
    movement_id: str
    client_request_id: Optional[str] = None
    wo_number: str
    part_number: str
    from_stage: str
    to_stage: str
    quantity_moved: int
    rejected_quantity: int
    available_wip_remaining: int
    to_stage_available_wip: int
    current_stage: str
    timestamp: datetime
    message: str

class MovementListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    movement_id: str
    client_request_id: Optional[str] = None
    source_type: Optional[str] = "SMES_UI"
    wo_number: str
    part_number: Optional[str] = None
    part_name: Optional[str] = None
    from_stage: str
    to_stage: str
    quantity_moved: int
    rejected_quantity: int
    machine_id: Optional[str] = None
    operator_name: Optional[str] = None
    shift: Optional[str] = None
    movement_date: Optional[str] = None
    movement_time: Optional[str] = None
    remarks: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime

class StageWIPDetail(BaseModel):
    stage: str
    ent_qty: int
    ok_qty: int
    inproc_qty: int
    onhand_qty: int
    rejected_qty: int
    available_wip: int
    target_qty: int
    status: str

class WOWIPRow(BaseModel):
    wo_id: str
    wo_number: str
    part_number: str
    part_name: Optional[str] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    order_qty: int
    current_stage: str
    status: str
    stage_wips: dict[str, int]
    stage_inproc: Optional[dict[str, int]] = None
    stage_onhand: Optional[dict[str, int]] = None
    total_wip: int
    last_updated: Optional[datetime] = None

class WIPMatrixResponse(BaseModel):
    stages: List[str]
    work_orders: List[WOWIPRow]
    stage_totals: dict[str, int]
    stage_inproc_totals: Optional[dict[str, int]] = None
    stage_onhand_totals: Optional[dict[str, int]] = None
    grand_total_wip: int

class ReconciliationItem(BaseModel):
    wo_number: str
    released_qty: int
    total_wip: int
    total_rejected: int
    dispatched_qty: int
    accounted_qty: int
    variance: int
    is_balanced: bool
    details: str

class PlantReconciliationResponse(BaseModel):
    total_work_orders: int
    balanced_work_orders: int
    mismatched_work_orders: int
    total_released_qty: int
    total_wip_qty: int
    total_rejected_qty: int
    total_dispatched_qty: int
    reconciliations: List[ReconciliationItem]
    is_plant_balanced: bool
