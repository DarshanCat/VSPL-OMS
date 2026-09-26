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
# Machine Master
# ---------------------------------------------------------------------------

class MachineCreate(BaseModel):
    machine_code: str = Field(..., max_length=100)
    machine_name: str = Field(..., max_length=300)
    department: Optional[str] = Field(None, max_length=200)


class MachineUpdate(BaseModel):
    id: str
    machine_name: Optional[str] = Field(None, max_length=300)
    department: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None


class MachineOut(BaseModel):
    id: str
    machine_code: str
    machine_name: str
    department: Optional[str] = None
    is_active: bool = True


# ---------------------------------------------------------------------------
# Shift Master
# ---------------------------------------------------------------------------

class ShiftCreate(BaseModel):
    shift_code: str = Field(..., max_length=100)
    shift_name: str = Field(..., max_length=300)
    start_time: Optional[str] = Field(None, max_length=20)
    end_time: Optional[str] = Field(None, max_length=20)


class ShiftUpdate(BaseModel):
    id: str
    shift_name: Optional[str] = Field(None, max_length=300)
    start_time: Optional[str] = Field(None, max_length=20)
    end_time: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class ShiftOut(BaseModel):
    id: str
    shift_code: str
    shift_name: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    is_active: bool = True


# ---------------------------------------------------------------------------
# Operator Master
# ---------------------------------------------------------------------------

class OperatorCreate(BaseModel):
    user_id: Optional[str] = Field(None, description="Link to an existing authenticated User, if one exists")
    employee_code: Optional[str] = Field(None, max_length=100)
    display_name: str = Field(..., max_length=300)


class OperatorUpdate(BaseModel):
    id: str
    employee_code: Optional[str] = Field(None, max_length=100)
    display_name: Optional[str] = Field(None, max_length=300)
    is_active: Optional[bool] = None


class OperatorOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    employee_code: Optional[str] = None
    display_name: str
    is_active: bool = True


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
