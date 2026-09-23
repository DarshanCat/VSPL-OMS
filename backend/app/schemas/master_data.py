from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Customer Master
# ---------------------------------------------------------------------------

class CustomerCreate(BaseModel):
    customer_code: str = Field(..., max_length=100)
    name: str = Field(..., max_length=300)
    address: Optional[str] = Field(None, max_length=1000)
    gst: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=200)
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    is_active: bool = True


class CustomerUpdate(BaseModel):
    id: str
    address: Optional[str] = Field(None, max_length=1000)
    gst: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=200)
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None


class CustomerOut(BaseModel):
    id: str
    customer_code: str
    name: str
    address: Optional[str] = None
    gst: Optional[str] = None
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True


# ---------------------------------------------------------------------------
# PO Master
# ---------------------------------------------------------------------------

class POLineCreate(BaseModel):
    part_number: str = Field(..., max_length=100)
    po_qty: int = Field(..., gt=0, le=1_000_000)
    required_date: Optional[date] = None


class POMasterCreate(BaseModel):
    po_number: str = Field(..., max_length=200)
    customer_code: str = Field(..., max_length=100)
    po_date: Optional[date] = None
    validity_date: Optional[date] = None
    lines: List[POLineCreate] = Field(..., min_length=1)


class POLineOut(BaseModel):
    id: str
    part_number: str
    po_qty: int
    allocated_qty: int
    available_qty: int
    required_date: Optional[date] = None


class POMasterOut(BaseModel):
    id: str
    po_number: str
    customer_code: str
    customer_name: str
    po_date: Optional[date] = None
    validity_date: Optional[date] = None
    status: str
    lines: List[POLineOut] = []


# ---------------------------------------------------------------------------
# Schedule Master
# ---------------------------------------------------------------------------

class ScheduleCreate(BaseModel):
    customer_code: str = Field(..., max_length=100)
    part_number: str = Field(..., max_length=100)
    scheduled_qty: int = Field(..., gt=0, le=1_000_000)
    required_date: Optional[date] = None
    customer_schedule_ref: Optional[str] = Field(None, max_length=200)


class ScheduleOut(BaseModel):
    id: str
    schedule_number: str
    customer_code: str
    customer_name: str
    part_number: str
    scheduled_qty: int
    required_date: Optional[date] = None
    customer_schedule_ref: Optional[str] = None
    po_status: str
    linked_oar_number: Optional[str] = None


# ---------------------------------------------------------------------------
# PO <-> Schedule Matching
# ---------------------------------------------------------------------------

class MatchCandidate(BaseModel):
    schedule_id: str
    schedule_number: str
    part_number: str
    scheduled_qty: int
    required_date: Optional[date] = None
    oar_number: Optional[str] = None
    quantity_match: str  # "EXACT" | "PO_BELOW_SCHEDULE" | "PO_ABOVE_SCHEDULE"
    mismatch_message: Optional[str] = None


class DuplicateCheckResult(BaseModel):
    has_candidate: bool
    candidates: List[MatchCandidate] = []
    message: Optional[str] = None


class MatchConfirmRequest(BaseModel):
    po_line_id: str
    schedule_id: str
    acknowledge_mismatch: bool = Field(
        False,
        description="Must be true to proceed when quantities differ. Exact matches never need this.",
    )


class MatchConfirmResponse(BaseModel):
    success: bool
    oar_number: str
    schedule_number: str
    po_number: str
    quantity_match: str
    message: str
