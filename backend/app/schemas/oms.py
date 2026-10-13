from pydantic import BaseModel, Field
from typing import Optional, List, Union
from datetime import date, datetime

class OMSRunResult(BaseModel):
    status: str  # "success" | "blocked"
    message: str
    master_file: Optional[str] = None
    report_file: Optional[str] = None
    download_master: Optional[str] = None
    download_report: Optional[str] = None

class WOOarLinkRow(BaseModel):
    wo_id: str = Field(..., description="Authoritative team-assigned Work Order ID e.g. WO-17597")
    oar_no: Optional[str] = Field(None, description="Optional/unverified OAR number e.g. OAR-4075")
    customer: str = Field(..., description="Customer name or code")
    customer_po_number: str = Field(..., description="Customer PO or Schedule reference")
    part_no: str = Field(..., description="Customer or internal part number")
    grade: Optional[str] = Field("Standard", description="Material grade")
    po_quantity: Optional[int] = Field(None, description="Total PO quantity")
    wo_quantity: int = Field(..., description="Physical release quantity for this WO")
    cust_delivery_date: Optional[Union[date, datetime, str]] = Field(None, description="Customer delivery date or setup date")

class LinkException(BaseModel):
    type: str  # "missing_field", "oar_mismatch", "customer_mismatch", "system_error"
    detail: str
    wo_id: Optional[str] = None

class LinkResultItem(BaseModel):
    wo_id: str
    oar_no: Optional[str] = None
    status: str  # "linked", "already_linked", "exception"
    detail: Optional[str] = None

class LinkResult(BaseModel):
    total_processed: int
    linked_count: int
    already_linked_count: int
    created_oars_count: int
    exceptions_count: int
    linked: List[str] = Field(default_factory=list)
    already_linked: List[str] = Field(default_factory=list)
    created_oars: List[str] = Field(default_factory=list)
    exceptions: List[LinkException] = Field(default_factory=list)
    items: List[LinkResultItem] = Field(default_factory=list)