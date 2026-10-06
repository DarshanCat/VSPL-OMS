from typing import List, Optional, Any
from datetime import datetime, date
from pydantic import BaseModel, Field, ConfigDict

class HeatCreate(BaseModel):
    heat_number: str = Field(..., min_length=1, max_length=100, description="Furnace melt / heat batch number, e.g. H-26-0814")
    grade: str = Field(..., min_length=1, max_length=100, description="Metallurgy material grade, e.g. PB2 / CuSn11P")
    melt_date: Optional[date] = Field(None, description="Date of furnace melt / casting")
    status: Optional[str] = Field("ACTIVE", description="Heat status: ACTIVE, DEPLETED, QUARANTINED")
    tc_number: Optional[str] = Field(None, description="Test Certificate / Lab Report number")
    supplier_or_foundry: Optional[str] = Field(None, description="Foundry furnace cell or raw material supplier")
    remarks: Optional[str] = None


class HeatResponse(BaseModel):
    id: str
    heat_number: str
    grade: str
    melt_date: Optional[date] = None
    status: str
    tc_number: Optional[str] = None
    supplier_or_foundry: Optional[str] = None
    remarks: Optional[str] = None
    created_at: datetime
    total_allocated_qty: int = 0

    model_config = ConfigDict(from_attributes=True)


class HeatAllocationItem(BaseModel):
    heat_number: str = Field(..., min_length=1, description="Heat number to allocate from")
    allocated_qty: int = Field(..., gt=0, description="Number of pieces allocated from this heat")


class HeatAllocationCreate(BaseModel):
    allocations: List[HeatAllocationItem] = Field(..., min_length=1, description="List of heat allocations")
    stage: Optional[str] = Field("F1", description="Stage at which heat is allocated (default F1 - Foundry)")
    remarks: Optional[str] = None


class HeatAllocationResponseItem(BaseModel):
    id: str
    heat_number: str
    grade: str
    tc_number: Optional[str] = None
    allocated_qty: int
    stage: str
    allocated_at: datetime
    allocated_by: Optional[str] = None
    remarks: Optional[str] = None


class WOHeatAllocationResponse(BaseModel):
    wo_number: str
    allocations: List[HeatAllocationResponseItem]
    total_heat_allocated_qty: int


class StageTraceabilityItem(BaseModel):
    stage: str
    sequence: int
    target_qty: int
    ok_qty: int
    rejected_qty: int
    inproc_qty: int
    onhand_qty: int
    status: str


class DispatchTraceabilityItem(BaseModel):
    invoice_number: str
    dispatched_qty: int
    dispatch_date: Optional[datetime] = None
    customer_po: Optional[str] = None


class TraceabilityResponse(BaseModel):
    wo_number: str
    oar_number: Optional[str] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    customer_po: Optional[str] = None
    part_number: Optional[str] = None
    part_description: Optional[str] = None
    grade: Optional[str] = None
    physical_wo_qty: int
    current_stage: str
    status: str
    heats: List[HeatAllocationResponseItem] = []
    total_heat_allocated_qty: int = 0
    stage_progression: List[StageTraceabilityItem] = []
    dispatches: List[DispatchTraceabilityItem] = []
