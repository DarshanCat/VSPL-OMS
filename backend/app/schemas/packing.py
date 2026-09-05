from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class PackingQueueItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_order_id: str
    wo_number: str
    oar_number: Optional[str] = None
    customer_name: str
    part_number: str
    part_name: Optional[str] = None
    grade: Optional[str] = None
    order_qty: int
    fi_approved_qty: int
    available_for_packing: int
    received_qty: int
    packed_qty: int
    pending_qty: int
    ready_for_dispatch_qty: int
    dispatched_qty: int
    status: str
    updated_at: datetime

class PackingUpdateRequest(BaseModel):
    wo_number: str
    packed_quantity: int = Field(..., gt=0, description="Quantity to pack / complete BSR")
    box_count: Optional[int] = 1
    package_type: Optional[str] = "Standard Box"
    remarks: Optional[str] = None

class PackingUpdateResponse(BaseModel):
    success: bool
    wo_number: str
    packed_this_batch: int
    total_packed: int
    remaining_pending: int
    ready_for_dispatch: int
    message: str
