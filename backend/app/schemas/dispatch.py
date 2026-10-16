from typing import Optional, List
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
    unit_price: float = 0.0

class DispatchRequest(BaseModel):
    wo_number: str
    customer_po: Optional[str] = Field(None, max_length=200)
    invoice_number: str = Field(..., max_length=200, description="Invoice Number e.g. INV-2026-001")
    dispatched_quantity: int = Field(..., gt=0, le=1_000_000, description="Quantity to dispatch")
    unit_price: Optional[float] = Field(None, ge=0.0, description="Product selling price per piece")
    payment_status: Optional[str] = Field("UNPAID", description="UNPAID, PAID, PARTIALLY_PAID, OVERDUE")
    paid_amount: Optional[float] = Field(0.0, ge=0.0)
    payment_reference: Optional[str] = Field(None, max_length=200)
    vehicle_number: Optional[str] = Field(None, max_length=100)
    transporter: Optional[str] = Field(None, max_length=200)
    remarks: Optional[str] = Field(None, max_length=2000)
    client_request_id: Optional[str] = Field(None, description="Idempotency key to prevent duplicate submissions")

class DispatchResponse(BaseModel):
    success: bool
    invoice_number: str
    wo_number: str
    client_request_id: Optional[str] = None
    dispatched_quantity: int
    remaining_ready_for_dispatch: int
    unit_price: float = 0.0
    total_invoice_value: float = 0.0
    payment_status: str = "UNPAID"
    paid_amount: float = 0.0
    wo_status: str
    message: str

class DispatchHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_order_id: str
    wo_number: str
    customer_code: Optional[str] = None
    customer_name: str
    customer_po: str
    part_number: str
    invoice_number: str
    dispatched_qty: int
    dispatch_date: datetime
    dispatcher_name: Optional[str] = None
    unit_price: float = 0.0
    total_invoice_value: float = 0.0
    payment_status: str = "UNPAID"
    paid_amount: float = 0.0
    payment_date: Optional[datetime] = None
    payment_reference: Optional[str] = None
    payment_remarks: Optional[str] = None

class InvoicePaymentUpdate(BaseModel):
    payment_status: str = Field(..., description="Payment status: 'PAID', 'UNPAID', 'PARTIALLY_PAID', 'OVERDUE'")
    paid_amount: Optional[float] = Field(None, ge=0.0, description="Amount received")
    payment_date: Optional[datetime] = None
    payment_reference: Optional[str] = Field(None, max_length=200, description="UTR, Cheque number, Transaction ID")
    payment_remarks: Optional[str] = Field(None, max_length=1000)

class CustomerReturnCreate(BaseModel):
    customer_code: str = Field(..., description="Customer identifier")
    customer_name: Optional[str] = None
    customer_po: Optional[str] = None
    invoice_number: Optional[str] = None
    original_wo_number: Optional[str] = None
    part_number: str = Field(..., description="Returned part number")
    returned_qty: int = Field(..., gt=0, description="Returned quantity")
    unit_price: Optional[float] = Field(None, ge=0.0, description="Product value / selling price per piece")
    complaint_reason: str = Field(..., min_length=2, max_length=2000, description="Customer defect / complaint reason")
    conversion_wo_number: Optional[str] = Field(None, max_length=100, description="Custom Conversion WO ID (auto-generated if omitted)")
    entry_stage: str = Field("F1", description="Stage to enter conversion: F1, F2, F3, SP, FI")
    destination_oar_number: Optional[str] = Field(None, description="Destination OAR to credit replacement fulfillment")

class CustomerReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    return_number: str
    customer_code: str
    customer_name: str
    customer_po: Optional[str] = None
    invoice_number: Optional[str] = None
    original_wo_number: Optional[str] = None
    part_number: str
    returned_qty: int
    unit_price: float = 0.0
    total_return_value: float = 0.0
    complaint_reason: str
    complaint_date: datetime
    status: str
    conversion_wo_number: str
    entry_stage: str
    destination_oar_number: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime

class CustomerReturnResponse(BaseModel):
    success: bool
    return_number: str
    conversion_wo_number: str
    returned_qty: int
    unit_price: float
    total_return_value: float
    entry_stage: str
    destination_oar_number: Optional[str] = None
    message: str
