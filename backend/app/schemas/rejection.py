from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel, Field

class ExcessNonMovingCreate(BaseModel):
    wo_number: str = Field(..., description="Work Order the excess/non-moving material belongs to")
    stage: Optional[str] = Field(None, max_length=100)
    source_type: str = Field(..., description="EXCESS_PRODUCTION or NON_MOVING")
    qty: int = Field(..., gt=0, le=1_000_000)
    reason: str = Field(..., max_length=2000)
    remarks: Optional[str] = Field(None, max_length=2000)

class DispositionCreate(BaseModel):
    nc_number: str = Field(..., description="Rejection Tracking record ID e.g. NC-00001")
    action: str = Field(..., description="CONVERT_PART | SAME_PART | CWO | SCRAP | DEVIATION_ACCEPT")
    quantity: int = Field(..., gt=0, le=1_000_000)
    destination_oar_number: Optional[str] = Field(None, description="Required for CONVERT_PART / SAME_PART / CWO")
    entry_stage: Optional[str] = Field(None, description="Required for CONVERT_PART / SAME_PART / CWO")
    conversion_wo_number: Optional[str] = Field(None, max_length=100, description="Required for CONVERT_PART / SAME_PART / CWO")
    destination_customer_code: Optional[str] = Field(None, max_length=100, description="Used for DEVIATION_ACCEPT customer allocation")
    reason: str = Field(..., max_length=2000)
    remarks: Optional[str] = Field(None, max_length=2000)

class RejectionTypeCreate(BaseModel):
    code: str = Field(..., max_length=100, description="Stable natural key, e.g. DEF-POROSITY")
    name: str = Field(..., max_length=300)
    description: Optional[str] = Field(None, max_length=1000)

class RejectionTypeUpdate(BaseModel):
    id: str
    name: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = Field(None, max_length=1000)
    is_active: Optional[bool] = None

class RejectionTypeOut(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

class ReplacementCreate(BaseModel):
    nc_number: Optional[str] = Field(None, description="Rejection Tracking record ID e.g. NC-00001 (optional if oar_number is provided)")
    oar_number: Optional[str] = Field(None, description="OAR Number e.g. OAR-00001 (optional if nc_number is provided)")
    source_wo_number: Optional[str] = Field(None, description="Source Work Order Number")
    quantity: int = Field(..., gt=0, le=1_000_000)
    reason: str = Field(..., max_length=2000, description="Mandatory -- why a replacement WO is required")
    remarks: Optional[str] = Field(None, max_length=2000)

class ReplacementResponse(BaseModel):
    success: bool
    nc_number: Optional[str] = "N/A"
    replacement_wo_number: str
    original_wo_number: str
    oar_number: str
    quantity: int
    remaining_qty: int
    message: str

class DispositionOut(BaseModel):
    id: str
    action: str
    quantity: int
    destination_wo_number: Optional[str] = None
    destination_part_number: Optional[str] = None
    destination_customer_code: Optional[str] = None
    conversion_wo_number: Optional[str] = None
    authorized_by_name: Optional[str] = None
    remarks: Optional[str] = None
    created_at: datetime
    melting_status: Optional[str] = None
    melting_destination: Optional[str] = None
    melting_sent_by_name: Optional[str] = None
    melting_sent_at: Optional[datetime] = None
    melting_remarks: Optional[str] = None

class MeltingEntryCreate(BaseModel):
    disposition_id: str = Field(..., description="The SCRAP RejectionDisposition record being physically sent for melting")
    melting_destination: Optional[str] = Field(None, max_length=200, description="Furnace / melting bay identifier")
    remarks: Optional[str] = Field(None, max_length=2000)

class MeltingEntryResponse(BaseModel):
    success: bool
    disposition_id: str
    nc_number: str
    wo_number: str
    part_number: Optional[str] = None
    quantity: int
    melting_status: str
    melting_destination: Optional[str] = None
    sent_by: str
    sent_at: datetime
    message: str

class DispositionResponse(BaseModel):
    success: bool
    nc_number: str
    action: str
    quantity: int
    remaining_qty: int
    conversion_wo_number: Optional[str] = None
    message: str

class RejectionListItem(BaseModel):
    nc_number: str
    wo_number: str
    oar_number: Optional[str] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    part_number: Optional[str] = None
    stage: Optional[str] = None
    source_type: str
    qty: int
    consumed_qty: int
    remaining_qty: int
    reason: Optional[str] = None
    status: str
    disposition: Optional[str] = None
    date_raised: datetime

class RejectionSourceBlock(BaseModel):
    nc_number: str
    wo_number: str
    oar_number: Optional[str] = None
    part_number: Optional[str] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    production_stage: Optional[str] = None
    source_type: str
    original_quantity: int
    reason: Optional[str] = None
    responsibility: Optional[str] = None
    date_raised: datetime

class RejectionBalance(BaseModel):
    original_qty: int
    consumed_qty: int
    remaining_qty: int

class RejectionOutcomeBreakdown(BaseModel):
    another_part_qty: int = 0
    same_part_qty: int = 0
    cwo_qty: int = 0
    scrap_qty: int = 0
    deviation_accept_qty: int = 0
    remaining_qty: int = 0

class RejectionDetail(BaseModel):
    source: RejectionSourceBlock
    disposition_history: List[DispositionOut]
    balance: RejectionBalance
    final_outcome: RejectionOutcomeBreakdown
    status: str

class CWODetail(BaseModel):
    """A Conversion Work Order is a normal WorkOrder row (same authoritative WO
    architecture, same WO ID generation) created specifically to execute a conversion.
    This view assembles its full source lineage for display -- it invents nothing that
    isn't already stored on the WorkOrder / Conversion / NCRecord / RejectionDisposition
    rows."""
    wo_number: str
    source_part_number: Optional[str] = None
    source_wo_number: Optional[str] = None
    source_oar_number: Optional[str] = None
    source_nc_number: Optional[str] = None
    destination_part_number: Optional[str] = None
    source_qty: int
    converted_qty: int
    remaining_qty: int
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    reason: Optional[str] = None

class RejectionSummary(BaseModel):
    total_rejected: int
    total_excess: int
    total_non_moving: int
    total_converted: int
    total_scrap: int
    total_remaining: int
