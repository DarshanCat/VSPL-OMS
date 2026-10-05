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
    # The authoritative, user-facing input -- the Internal Part Number is NEVER
    # typed or chosen by the PO operator; it is resolved (or, for a genuinely new
    # part, generated) server-side from this value. See
    # MasterDataService.resolve_customer_part / POMasterService.create_po.
    customer_part_number: Optional[str] = Field(None, max_length=200)
    # Legacy/direct-API path only -- preserved so any existing caller that already
    # supplies the literal internal part_number keeps working unchanged. The PO
    # Master UI no longer sends this field.
    part_number: Optional[str] = Field(None, max_length=100)
    po_qty: int = Field(..., gt=0, le=1_000_000)
    required_date: Optional[date] = None

    # Deliberately NOT enforced here with a pydantic validator -- raising a plain
    # ValueError from a model_validator embeds the exception object itself in the
    # error's `ctx`, which this app's generic RequestValidationError handler
    # (app/main.py) cannot JSON-serialize. Enforced instead in
    # POMasterService.create_po, alongside its other HTTPException-raising
    # business-rule checks.


class POMasterCreate(BaseModel):
    po_number: str = Field(..., max_length=200)
    customer_code: str = Field(..., max_length=100)
    po_date: Optional[date] = None
    validity_date: Optional[date] = None
    lines: List[POLineCreate] = Field(..., min_length=1)


class POLineOut(BaseModel):
    id: str
    part_number: str
    customer_part_number: Optional[str] = None
    po_qty: int
    allocated_qty: int
    available_qty: int
    required_date: Optional[date] = None


class CustomerPartOut(BaseModel):
    customer_part_number: str
    part_number: str
    description: Optional[str] = None
    grade: Optional[str] = None


class ResolveCustomerPartRequest(BaseModel):
    customer_code: str = Field(..., max_length=100)
    customer_part_number: str = Field(..., max_length=200)


class ResolveCustomerPartResponse(BaseModel):
    customer_part_number: str
    resolved: bool
    part_number: Optional[str] = None
    is_new: bool
    message: str


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
