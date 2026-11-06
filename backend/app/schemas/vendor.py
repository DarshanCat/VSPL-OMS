from typing import Optional, List, Any
from pydantic import BaseModel, Field
from datetime import datetime


class VendorReceiveRequest(BaseModel):
    dispatch_id: str = Field(..., description="UUID of the vendor dispatch record")
    received_qty: int = Field(..., ge=1, description="Quantity of good parts received from vendor")
    scrap_qty: int = Field(0, ge=0, description="Quantity of rejected / scrap parts reported from vendor")
    inward_dc: Optional[str] = Field(None, max_length=100, description="Inward Delivery Challan / Invoice / Gate Pass #")
    remarks: Optional[str] = Field(None, max_length=1000, description="Inward remarks / inspection condition")


class VendorReceiveResponse(BaseModel):
    success: bool
    message: str
    dispatch_id: str
    wo_number: str
    received_qty: int
    scrap_qty: int
    status: str
    current_stage: str


class VendorDispatchItem(BaseModel):
    id: str
    work_order_id: Optional[str]
    wo_number: str
    oar_number: str
    customer_name: str
    part_number: str
    part_name: str
    dispatch_stage: str
    vendor_name: str
    dc_number: str
    dispatched_qty: int
    received_qty: int
    scrap_qty: int
    pending_qty: int
    status: str
    dispatched_at: datetime
    received_at: Optional[datetime]
    inward_dc_number: Optional[str]
    remarks: Optional[str]
    days_at_vendor: int


class VendorSummaryResponse(BaseModel):
    active_dispatches_count: int
    completed_dispatches_count: int
    total_pieces_at_vendor: int
    total_pieces_received: int
    active_vendor_count: int
