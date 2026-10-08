"""Response schemas for the Continuous Casting READ API (Phase 11C).

Nothing here is a second source of truth: every value is either a column of an existing China table (cached
balances included), a deterministic calculation over those columns, a figure derived from the append-only ledger,
or a relationship lookup. Lists share one envelope, mirroring PartMasterListResponse:
    {"items": [...], "total": N, "limit": L, "offset": O}
"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


# ------------------------------------------------------------------ materials
class CCMaterialOut(BaseModel):
    material_id: str
    material_code: str
    grade: str
    section: str
    stock_dimension_a_mm: int
    stock_dimension_b_mm: Optional[int] = None
    description: Optional[str] = None
    is_active: bool
    referenced: bool
    inward_count: int
    routing_count: int
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CCMaterialListResponse(BaseModel):
    items: List[CCMaterialOut]
    total: int
    limit: int
    offset: int


class CCMaterialStockSummaryOut(BaseModel):
    material_id: str
    material_code: str
    grade: str
    section: str
    stock_dimension_a_mm: int
    stock_dimension_b_mm: Optional[int] = None
    standard_length_mm: Optional[int] = None
    size_display: str
    unit_count: int
    total_length_mm: int
    remaining_length_mm: int
    reserved_length_mm: int
    issued_length_mm: int
    consumed_length_mm: int
    scrapped_length_mm: int
    free_length_mm: int
    documented_weight_kg: Optional[float] = None
    status: str
    inward_count: int
    inward_numbers: List[str] = []


class CCMaterialStockSummaryTotals(BaseModel):
    total_bars: int
    total_length_mm: int
    total_weight_kg: float


class CCMaterialStockSummaryResponse(BaseModel):
    items: List[CCMaterialStockSummaryOut]
    total: int
    totals: CCMaterialStockSummaryTotals
    limit: int
    offset: int


# ------------------------------------------------------------------ inwards
class CCInwardStockOut(BaseModel):
    inward_id: str
    inward_number: str
    material_id: str
    material_code: str
    grade: str
    section: str
    stock_dimension_a_mm: int
    stock_dimension_b_mm: Optional[int] = None
    received_piece_count: int
    received_total_length_mm: int
    grn_reference: Optional[str] = None
    qa_status: str
    location: Optional[str] = None
    received_at: Optional[datetime] = None
    # sums over the inward's stock units (cached unit balances); free = remaining - reserved - issued
    unit_count: int
    remaining_length_mm: int
    reserved_length_mm: int
    issued_length_mm: int
    consumed_length_mm: int
    scrapped_length_mm: int
    free_length_mm: int


class CCInwardListResponse(BaseModel):
    items: List[CCInwardStockOut]
    total: int
    limit: int
    offset: int


class CCQADecisionInfo(BaseModel):
    decision: str
    previous_qa_status: Optional[str] = None
    reason: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None


class CCConservation(BaseModel):
    """Informational only. accounted = sum(remaining + consumed + scrapped) over the units;
    expected = received - sum(ADJUSTMENT_OUT) + sum(ADJUSTMENT_IN) from the ledger."""
    accounted_length_mm: int
    expected_length_mm: int
    adjustments_in_mm: int
    adjustments_out_mm: int
    consistent: bool


class CCInwardDetail(CCInwardStockOut):
    remarks: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    original_received_length_mm: int
    physical_piece_count: int
    # From the audit history (the inward has no QA-decision columns); None while still PENDING_QA.
    qa_decision: Optional[CCQADecisionInfo] = None
    conservation: CCConservation


# ------------------------------------------------------------------ allocations / routings
class CCAllocationOut(BaseModel):
    allocation_id: str
    allocation_number: str
    routing_id: str
    routing_version: int
    routing_status: str
    work_order_id: str
    wo_number: str
    inward_id: str
    inward_number: str
    stock_unit_id: str
    stock_unit_number: str
    planned_length_mm: int
    reserved_length_mm: int
    issued_length_mm: int
    consumed_length_mm: int
    # planned - reserved - issued - consumed (the plan guard's own arithmetic)
    plan_remaining_length_mm: int
    status: str


class CCAllocationListResponse(BaseModel):
    items: List[CCAllocationOut]
    total: int
    limit: int
    offset: int


class CCRoutingOut(BaseModel):
    routing_id: str
    work_order_id: str
    wo_number: str
    version: int
    status: str
    is_active: bool
    material_source: str
    validated_material_id: Optional[str] = None
    validated_material_code: Optional[str] = None
    required_grade: Optional[str] = None
    required_section: Optional[str] = None
    finished_dimension_a_mm: Optional[int] = None
    finished_dimension_b_mm: Optional[int] = None
    finished_axial_length_mm: Optional[int] = None
    machining_stock_a_mm: Optional[int] = None
    machining_stock_b_mm: Optional[int] = None
    blank_length_mm: Optional[int] = None
    planned_blanks: Optional[int] = None
    planned_cuts: Optional[int] = None
    kerf_mm: Optional[int] = None
    end_trim_mm: Optional[int] = None
    gross_required_length_mm: Optional[int] = None
    validated_by: Optional[str] = None
    validated_at: Optional[datetime] = None
    superseded_at: Optional[datetime] = None
    superseded_by: Optional[str] = None
    supersede_reason: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    allocation_count: int


class CCRoutingListResponse(BaseModel):
    items: List[CCRoutingOut]
    total: int
    limit: int
    offset: int


class CCRoutingDetail(CCRoutingOut):
    allocations: List[CCAllocationOut]


# ------------------------------------------------------------------ stock units
class CCStockUnitOut(BaseModel):
    unit_id: str
    unit_number: str
    inward_id: str
    inward_number: str
    inward_qa_status: str
    material_id: str
    material_code: str
    parent_unit_id: Optional[str] = None
    parent_unit_number: Optional[str] = None
    original_length_mm: int
    remaining_length_mm: int
    reserved_length_mm: int
    issued_length_mm: int
    consumed_length_mm: int
    scrapped_length_mm: int
    free_length_mm: int
    # One physical bar per StockUnit (the frozen model; there is no piece-quantity column).
    piece_quantity: int
    status: str
    location: Optional[str] = None
    created_at: Optional[datetime] = None
    allocation_eligible: bool
    allocation_ineligible_reason: Optional[str] = None


class CCStockUnitListResponse(BaseModel):
    items: List[CCStockUnitOut]
    total: int
    limit: int
    offset: int


class CCUnitChild(BaseModel):
    unit_id: str
    unit_number: str
    original_length_mm: int
    remaining_length_mm: int
    status: str


class CCLastHold(BaseModel):
    movement_type: str
    transaction_number: str
    reason: Optional[str] = None
    performed_by: Optional[str] = None
    created_at: Optional[datetime] = None


class CCUnitIntegrity(BaseModel):
    """Informational: the cached balances next to what the ledger gives. Never an error, never a repair."""
    consistent: bool
    ledger_remaining_length_mm: int
    ledger_reserved_length_mm: int
    ledger_issued_length_mm: int
    ledger_consumed_length_mm: int
    ledger_scrapped_length_mm: int


class CCStockUnitDetail(CCStockUnitOut):
    children: List[CCUnitChild]
    net_adjustment_mm: int
    last_hold_event: Optional[CCLastHold] = None
    integrity: CCUnitIntegrity
    allocations: List[CCAllocationOut]


# ------------------------------------------------------------------ ledger
class CCLedgerOut(BaseModel):
    transaction_number: str
    movement_type: str
    inward_id: str
    inward_number: str
    stock_unit_id: str
    stock_unit_number: str
    allocation_id: Optional[str] = None
    allocation_number: Optional[str] = None
    routing_id: Optional[str] = None
    routing_version: Optional[int] = None
    wo_number: Optional[str] = None
    length_mm: int
    piece_qty: Optional[int] = None
    unit_remaining_after_mm: Optional[int] = None
    related_stock_unit_id: Optional[str] = None
    related_stock_unit_number: Optional[str] = None
    nc_record_id: Optional[str] = None
    nc_number: Optional[str] = None
    reason: Optional[str] = None
    reference: Optional[str] = None
    performed_by: Optional[str] = None
    created_at: Optional[datetime] = None


class CCLedgerListResponse(BaseModel):
    items: List[CCLedgerOut]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------------ cut results
class CCCutResultOut(BaseModel):
    cut_result_id: str
    cut_number: str
    ledger_transaction_number: Optional[str] = None
    work_order_id: str
    wo_number: str
    routing_id: str
    routing_version: int
    routing_status: str
    allocation_id: str
    allocation_number: str
    stock_unit_id: str
    stock_unit_number: str
    inward_number: str
    planned_blanks: int
    actual_cuts: int
    actual_good_blanks: int
    rejected_blanks: int
    blank_length_mm: int
    kerf_mm: int
    end_trim_mm: int
    consumed_length_mm: int
    reconciliation_status: str
    variance_mm: Optional[int] = None
    remarks: Optional[str] = None
    performed_by: Optional[str] = None
    created_at: Optional[datetime] = None
    # The Phase 10 gate's own conditions, evaluated for this one record.
    usable_for_oms: bool


class CCCutResultListResponse(BaseModel):
    items: List[CCCutResultOut]
    total: int
    limit: int
    offset: int


class CCCutAvailableOut(BaseModel):
    ledger_transaction_number: str
    consumed_length_mm: int
    allocation_id: str
    allocation_number: str
    stock_unit_id: str
    stock_unit_number: str
    routing_id: str
    routing_version: int
    routing_status: str
    wo_number: str
    created_at: Optional[datetime] = None
    # The routing's cutting context, for the Record Cut Result form. No blank count is calculated or suggested.
    planned_blanks: int
    blank_length_mm: int
    kerf_mm: int
    planned_cuts: Optional[int] = None
    routing_blanks_recorded: int
    routing_blanks_remaining_in_plan: int


class CCCutAvailableListResponse(BaseModel):
    items: List[CCCutAvailableOut]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------------ gate status
class CCGateStatus(BaseModel):
    """Informational view of the Phase 10 material gate for one Work Order. Never mutates anything."""
    wo_number: str
    gate_applies: bool
    material_source: Optional[str] = None
    routing_id: Optional[str] = None
    routing_version: Optional[int] = None
    first_route_stage: Optional[str] = None
    first_stage_valid: Optional[bool] = None
    planned_blanks: Optional[int] = None
    recorded_blanks: Optional[int] = None
    usable_good_blanks: Optional[int] = None
    first_stage_good_qty: Optional[int] = None
    first_stage_rejected_qty: Optional[int] = None
    remaining_capacity: Optional[int] = None
    verdict: str
    reasons: List[str]


# ------------------------------------------------------------------ traceability
class CCTraceUnit(BaseModel):
    unit_id: str
    unit_number: str
    parent_unit_number: Optional[str] = None
    original_length_mm: int
    remaining_length_mm: int
    reserved_length_mm: int
    issued_length_mm: int
    consumed_length_mm: int
    scrapped_length_mm: int
    free_length_mm: int
    status: str
    allocations: List[CCAllocationOut]


class CCTraceInwardRollup(BaseModel):
    inward_id: str
    inward_number: str
    unit_count: int
    allocation_count: int
    planned_length_mm: int
    reserved_length_mm: int
    issued_length_mm: int
    consumed_length_mm: int


class CCTraceWorkOrderRollup(BaseModel):
    wo_number: str
    routing_versions: List[int]
    active_routing_version: Optional[int] = None
    allocation_count: int
    planned_length_mm: int
    reserved_length_mm: int
    issued_length_mm: int
    consumed_length_mm: int


class CCTraceInward(BaseModel):
    inward: CCInwardDetail
    units: List[CCTraceUnit]
    work_orders: List[CCTraceWorkOrderRollup]
    cut_results: List[CCCutResultOut]
    ledger_totals_by_movement: dict
    recent_ledger: List[CCLedgerOut]
    # explicit bounds
    units_total: int
    allocations_total: int
    cut_results_total: int
    ledger_rows_total: int
    truncated: bool
    limitations: List[str]


class CCTraceRouting(BaseModel):
    routing: CCRoutingOut
    allocations: List[CCAllocationOut]


class CCTraceWorkOrder(BaseModel):
    wo_number: str
    work_order_id: str
    routings: List[CCRoutingOut]
    active_routing_version: Optional[int] = None
    allocations: List[CCAllocationOut]
    inwards: List[CCTraceInwardRollup]
    units: List[CCTraceUnit]
    cut_results: List[CCCutResultOut]
    usable_good_blanks: Optional[int] = None
    allocations_total: int
    cut_results_total: int
    truncated: bool
    limitations: List[str]
