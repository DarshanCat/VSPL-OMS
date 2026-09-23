from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict
from app.models.order import OrderStatus

class OrderIntakeCreate(BaseModel):
    customer_code: str = Field(..., max_length=100)
    customer_name: str = Field(..., max_length=300)
    customer_po: str = Field(..., max_length=200)
    part_number: str = Field(..., max_length=100)
    grade: Optional[str] = Field("Standard", max_length=100)
    part_description: Optional[str] = Field("", max_length=1000)
    po_quantity: int = Field(..., gt=0, le=1_000_000)
    max_batch_size: int = Field(..., gt=0, le=1_000_000)
    delivery_date: Optional[date] = None
    order_type: Optional[str] = Field("Standard", max_length=100)
    status: OrderStatus = OrderStatus.ACCEPT
    remarks: Optional[str] = Field(None, max_length=2000)
    wo_quantities: Optional[List[int]] = Field(
        None,
        max_length=100,
        description=(
            "Optional explicit WO quantity split (e.g. [400, 300, 200, 100]). Must sum "
            "exactly to po_quantity, with every value > 0. When omitted, falls back to "
            "the existing automatic max_batch_size-driven split (unchanged behavior)."
        ),
    )
    # Demand-source linkage -- all optional, all default to the pre-existing behavior
    # (a plain PO-sourced OAR) when omitted, so every existing caller is unaffected.
    source_type: Optional[str] = Field("po", description="'po' or 'schedule'.")
    po_line_id: Optional[str] = Field(None, description="Links this OAR to a specific PO Master line when source_type='po' via the structured PO workflow.")
    schedule_id: Optional[str] = Field(None, description="Links this OAR to a Schedule Master record when source_type='schedule'.")

class OrderIntakeResponse(BaseModel):
    success: bool
    oar_number: str
    order_id: str
    wos_created: List[str]
    wo_quantities: List[int] = []
    total_qty: int
    source_type: str = "po"
    oar_po_status: Optional[str] = None
    message: str

class WOReleaseCreate(BaseModel):
    wo_number: str
    physical_wo_qty: int = Field(..., gt=0, le=1_000_000)
    route_stages: List[str] = Field(..., max_length=50, description="Ordered list of stages e.g. ['F1', 'F2', 'F3', 'SP', 'FI', 'PACKING', 'DISPATCH']")
    remarks: Optional[str] = Field(None, max_length=2000)

class WOReleaseResponse(BaseModel):
    success: bool
    wo_number: str
    released_qty: int
    route: str
    stage_targets: dict[str, int]
    message: str

class ConversionCreate(BaseModel):
    conversion_wo_number: str = Field(..., max_length=100, description="Unique planner-assigned ID e.g. C-0021")
    source_wo_number: str
    destination_oar_number: str
    dest_part_number: Optional[str] = Field(None, max_length=100)
    quantity: int = Field(..., gt=0, le=1_000_000)
    entry_stage: str
    reason: str = Field(..., max_length=2000)

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
    defect_code: str = Field(..., max_length=100)
    qty: int = Field(..., gt=0, le=1_000_000)
    root_cause: Optional[str] = Field(None, max_length=2000)
    disposition: Optional[str] = Field("Scrap", max_length=100)
    responsibility: Optional[str] = Field("Production", max_length=100)
    remarks: Optional[str] = Field(None, max_length=2000)

class NCRecordUpdate(BaseModel):
    nc_number: str
    status: str
    root_cause: Optional[str] = Field(None, max_length=2000)
    disposition: Optional[str] = Field(None, max_length=100)
    remarks: Optional[str] = Field(None, max_length=2000)

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
