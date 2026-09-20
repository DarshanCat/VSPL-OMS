from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class DispatchQueueItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_order_id: str
    wo_number: str
    oar_number: Optional[str] = None
    customer_code: str
    customer_name: str
    customer_po: str
    part_number: str
    part_name: Optional[str] = None
    order_qty: int
    packed_completed_qty: int
    ready_for_dispatch_qty: int
    already_dispatched_qty: int
    status: str

class DispatchRequest(BaseModel):
    wo_number: str
    customer_po: Optional[str] = None
    invoice_number: str = Field(..., description="Invoice Number e.g. INV-2026-001")
    dispatched_quantity: int = Field(..., gt=0, description="Quantity to dispatch")
    vehicle_number: Optional[str] = None
    transporter: Optional[str] = None
    remarks: Optional[str] = None
    client_request_id: Optional[str] = Field(None, description="Idempotency key to prevent duplicate submissions")

class DispatchResponse(BaseModel):
    success: bool
    invoice_number: str
    wo_number: str
    client_request_id: Optional[str] = None
    dispatched_quantity: int
    remaining_ready_for_dispatch: int
    wo_status: str
    message: str

class DispatchHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_order_id: str
    wo_number: str
    customer_name: str
    customer_po: str
    part_number: str
    invoice_number: str
    dispatched_qty: int
    dispatch_date: datetime
    dispatcher_name: Optional[str] = None
