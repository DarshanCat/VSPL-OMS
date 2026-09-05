from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict
from app.models.order import OrderStatus

class OrderIntakeCreate(BaseModel):
    customer_code: str
    customer_name: str
    customer_po: str
    part_number: str
    grade: Optional[str] = "Standard"
    part_description: Optional[str] = ""
    po_quantity: int = Field(..., gt=0)
    max_batch_size: int = Field(..., gt=0)
    delivery_date: Optional[date] = None
    order_type: Optional[str] = "Standard"
    status: OrderStatus = OrderStatus.ACCEPT
    remarks: Optional[str] = None

class OrderIntakeResponse(BaseModel):
    success: bool
    oar_number: str
    order_id: str
    wos_created: List[str]
    total_qty: int
    message: str

class WOReleaseCreate(BaseModel):
    wo_number: str
    physical_wo_qty: int = Field(..., gt=0)
    route_stages: List[str] = Field(..., description="Ordered list of stages e.g. ['F1', 'F2', 'F3', 'SP', 'FI', 'PACKING', 'DISPATCH']")
    remarks: Optional[str] = None

class WOReleaseResponse(BaseModel):
    success: bool
    wo_number: str
    released_qty: int
    route: str
    stage_targets: dict[str, int]
    message: str

class ConversionCreate(BaseModel):
    conversion_wo_number: str = Field(..., description="Unique planner-assigned ID e.g. C-0021")
    source_wo_number: str
    destination_oar_number: str
    dest_part_number: Optional[str] = None
    quantity: int = Field(..., gt=0)
    entry_stage: str
    reason: str

class ConversionResponse(BaseModel):
    success: bool
    conversion_wo_number: str
    source_wo_number: str
    quantity: int
    entry_stage: str
    message: str

class NCRecordCreate(BaseModel):
    wo_number: str
    stage: str
    defect_code: str
    qty: int = Field(..., gt=0)
    root_cause: Optional[str] = None
    disposition: Optional[str] = "Scrap"
    responsibility: Optional[str] = "Production"
    remarks: Optional[str] = None

class NCRecordUpdate(BaseModel):
    nc_number: str
    status: str
    root_cause: Optional[str] = None
    disposition: Optional[str] = None
    remarks: Optional[str] = None

class NCRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nc_number: str
    wo_number: str
    part_number: str
    stage: str
    defect_code: str
    qty: int
    root_cause: Optional[str] = None
    disposition: Optional[str] = None
    responsibility: Optional[str] = None
    status: str
    days_open: int
    date_raised: datetime
    date_closed: Optional[datetime] = None
    remarks: Optional[str] = None
