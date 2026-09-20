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
    packed_quantity: int = Field(..., gt=0, le=1_000_000, description="Quantity to pack / complete BSR")
    box_count: Optional[int] = Field(1, ge=0, le=100_000)
    package_type: Optional[str] = Field("Standard Box", max_length=100)
    remarks: Optional[str] = Field(None, max_length=2000)
    client_request_id: Optional[str] = Field(None, description="Idempotency key to prevent duplicate submissions")

class PackingUpdateResponse(BaseModel):
    success: bool
    wo_number: str
    client_request_id: Optional[str] = None
    packed_this_batch: int
    total_packed: int
    remaining_pending: int
    ready_for_dispatch: int
    message: str
