import uuid
from typing import Annotated, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

# Positive whole millimetres, bounded only by the 32-bit INTEGER column (a database type
# bound, not a business limit -- the specification sets no maximum bar length or bar count).
INT32_MAX = 2_147_483_647
BarLengthMm = Annotated[int, Field(gt=0, le=INT32_MAX)]


class CCInwardCreate(BaseModel):
    """One homogeneous inward line: N physical bars of one material. `unit_lengths_mm` has
    one entry per bar ("17 bars x 1000 mm" is [1000] * 17); piece count and total length
    are DERIVED from it. The optional received_* / dimension fields are the GRN document's
    declared figures and are only cross-checked, never trusted over the unit list.

    There is deliberately no qa_status: every inward is created PENDING_QA, and acceptance
    comes from the existing quality process, never from whoever posts the receipt."""
    model_config = ConfigDict(extra="forbid")

    material_id: uuid.UUID
    unit_lengths_mm: List[BarLengthMm] = Field(..., min_length=1)
    received_piece_count: Optional[int] = Field(None, gt=0)
    received_total_length_mm: Optional[int] = Field(None, gt=0)
    stock_dimension_a_mm: Optional[int] = Field(None, gt=0)
    stock_dimension_b_mm: Optional[int] = Field(None, gt=0)
    grn_reference: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=100)
    remarks: Optional[str] = Field(None, max_length=2000)


PositiveMm = Annotated[int, Field(gt=0, le=INT32_MAX)]
NonNegativeMm = Annotated[int, Field(ge=0, le=INT32_MAX)]


class CCRoutingCreate(BaseModel):
    """Continuous-casting routing for an EXISTING OMS Work Order (never creates one).
    All lengths are whole millimetres. blank_length_mm and gross_required_length_mm are
    always derived by the service and cannot be supplied:
      blank_length_mm          = finished_axial_length_mm + machining_stock_a_mm + machining_stock_b_mm
      gross_required_length_mm = planned_blanks * blank_length_mm + planned_cuts * kerf_mm + end_trim_mm
    `end_trim_mm` is the TOTAL end trim for the routing."""
    model_config = ConfigDict(extra="forbid")

    wo_number: str = Field(..., min_length=1, max_length=100)
    validated_material_id: uuid.UUID
    required_grade: str = Field(..., min_length=1, max_length=100)
    required_section: str = Field(..., min_length=1, max_length=100)
    finished_dimension_a_mm: PositiveMm
    finished_dimension_b_mm: Optional[PositiveMm] = None
    finished_axial_length_mm: PositiveMm
    machining_stock_a_mm: NonNegativeMm
    machining_stock_b_mm: NonNegativeMm
    planned_blanks: PositiveMm
    planned_cuts: NonNegativeMm
    kerf_mm: NonNegativeMm
    end_trim_mm: NonNegativeMm


class CCRoutingSupersede(CCRoutingCreate):
    """Same fields as a new routing, plus why the ACTIVE one is being replaced."""
    reason: str = Field(..., min_length=1, max_length=500)


class CCRoutingResult(BaseModel):
    success: bool
    routing_id: str
    wo_number: str
    version: int
    status: str
    material_source: str
    validated_material_code: str
    blank_length_mm: int
    gross_required_length_mm: int
    planned_blanks: int
    planned_cuts: int
    kerf_mm: int
    end_trim_mm: int
    superseded_version: Optional[int] = None
    message: str


class CCAllocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routing_id: uuid.UUID
    stock_unit_id: uuid.UUID
    planned_length_mm: PositiveMm


class CCAllocationResult(BaseModel):
    success: bool
    allocation_id: str
    allocation_number: str
    routing_id: str
    routing_version: int
    wo_number: str
    stock_unit_number: str
    inward_number: str
    planned_length_mm: int
    status: str
    # Information only. Allocation plans; it reserves nothing.
    reserved_length_mm: int
    unit_free_length_mm: int
    unit_available_for_planning_mm: int
    routing_gross_required_length_mm: int
    routing_planned_total_mm: int
    message: str


class CCReserveCreate(BaseModel):
    """Reserve `length_mm` of an allocation's stock. routing_id is required so a stale caller
    holding an old routing's allocation is rejected rather than silently accepted."""
    model_config = ConfigDict(extra="forbid")

    routing_id: uuid.UUID
    allocation_id: uuid.UUID
    length_mm: PositiveMm
    reason: Optional[str] = Field(None, max_length=500)


class CCReleaseCreate(BaseModel):
    """Release `length_mm` of currently RESERVED (never issued or consumed) stock."""
    model_config = ConfigDict(extra="forbid")

    routing_id: uuid.UUID
    allocation_id: uuid.UUID
    length_mm: PositiveMm
    reason: Optional[str] = Field(None, max_length=500)


class CCIssueCreate(BaseModel):
    """Issue `length_mm` of RESERVED stock to production. A physical Stores operation, so the
    request names the stock unit being handed over as well as the routing and allocation; all
    three must agree with each other."""
    model_config = ConfigDict(extra="forbid")

    routing_id: uuid.UUID
    allocation_id: uuid.UUID
    stock_unit_id: uuid.UUID
    length_mm: PositiveMm
    reason: Optional[str] = Field(None, max_length=500)


class CCCutConsumeCreate(BaseModel):
    """Record the ACTUAL length cut (consumed) from ISSUED stock, in whole millimetres. Like
    ISSUE it names the physical unit, and routing, allocation and unit must all agree."""
    model_config = ConfigDict(extra="forbid")

    routing_id: uuid.UUID
    allocation_id: uuid.UUID
    stock_unit_id: uuid.UUID
    length_mm: PositiveMm
    reason: Optional[str] = Field(None, max_length=500)


class CCReturnCreate(BaseModel):
    """Hand ISSUED, not-yet-cut stock back to the store. A physical Stores operation, so it
    names the inward and unit being handed back as well as the routing and allocation; all four
    must agree. Returned length simply becomes free again (issued - X)."""
    model_config = ConfigDict(extra="forbid")

    routing_id: uuid.UUID
    allocation_id: uuid.UUID
    stock_unit_id: uuid.UUID
    inward_id: uuid.UUID
    length_mm: PositiveMm
    reason: Optional[str] = Field(None, max_length=500)


class CCSplitCreate(BaseModel):
    """Split `length_mm` of FREE length off a stock unit into one new child unit (a retained
    remnant). Names the unit and its inward; both must agree. No routing or allocation is
    involved -- reserved and issued length never moves. The child inherits the parent's
    inward, QA context and location."""
    model_config = ConfigDict(extra="forbid")

    stock_unit_id: uuid.UUID
    inward_id: uuid.UUID
    length_mm: PositiveMm
    reason: Optional[str] = Field(None, max_length=500)


class CCSplitResult(BaseModel):
    success: bool
    split_out_transaction_number: str
    split_in_transaction_number: str
    inward_id: str
    inward_number: str
    length_mm: int
    parent_unit_id: str
    parent_unit_number: str
    parent_status: str
    parent_remaining_length_mm: int
    parent_reserved_length_mm: int
    parent_issued_length_mm: int
    parent_consumed_length_mm: int
    parent_free_length_mm: int
    child_unit_id: str
    child_unit_number: str
    child_status: str
    child_original_length_mm: int
    child_remaining_length_mm: int
    child_free_length_mm: int
    child_location: Optional[str] = None
    # Physical status and allocation eligibility are separate answers (QA lives on the inward).
    child_allocation_eligible: bool
    child_allocation_ineligible_reason: Optional[str] = None
    # Re-derived from the ledger before commit.
    inward_total_length_mm: int
    inward_units_remaining_plus_consumed_mm: int
    reconciled: bool
    message: str


RequiredText500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
RequiredText200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
RequestKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
RequiredText100 = RequestKey


class CCHoldCreate(BaseModel):
    """Quarantine one unit (IN_STOCK -> ON_HOLD). Status only: no balance changes. The reason is
    mandatory; the reference (an NCR / QA note) is optional. Names the unit and its inward."""
    model_config = ConfigDict(extra="forbid")

    stock_unit_id: uuid.UUID
    inward_id: uuid.UUID
    reason: RequiredText500
    reference: Optional[RequiredText200] = None


class CCHoldReleaseCreate(CCHoldCreate):
    """Lift a quarantine (ON_HOLD -> IN_STOCK). Same fields as a hold."""


class CCScrapCreate(BaseModel):
    """Physically dispose of `length_mm` of FREE length (never reserved, issued or consumed length).
    Reason and reference are mandatory. nc_record_id is only a pointer: the NC Tracker remains the
    disposition authority. client_request_id is optional; a replay of the same key and request
    returns the original result instead of scrapping twice."""
    model_config = ConfigDict(extra="forbid")

    stock_unit_id: uuid.UUID
    inward_id: uuid.UUID
    length_mm: PositiveMm
    reason: RequiredText500
    reference: RequiredText200
    nc_record_id: Optional[uuid.UUID] = None
    client_request_id: Optional[RequestKey] = None


class CCAdjustmentCreate(BaseModel):
    """Correct the recorded physical length of a unit. The direction is the service method
    (adjust_out / adjust_in), never a signed number. Reason and reference (the evidence) are mandatory."""
    model_config = ConfigDict(extra="forbid")

    stock_unit_id: uuid.UUID
    inward_id: uuid.UUID
    length_mm: PositiveMm
    reason: RequiredText500
    reference: RequiredText200
    client_request_id: Optional[RequestKey] = None


class CCUnitMovementResult(BaseModel):
    """Result of HOLD, HOLD_RELEASE, SCRAP, ADJUSTMENT_IN or ADJUSTMENT_OUT."""
    success: bool
    movement_type: str
    ledger_transaction_number: str
    replayed: bool = False
    inward_id: str
    inward_number: str
    stock_unit_id: str
    stock_unit_number: str
    length_mm: int
    unit_status: str
    unit_remaining_length_mm: int
    unit_reserved_length_mm: int
    unit_issued_length_mm: int
    unit_consumed_length_mm: int
    unit_scrapped_length_mm: int
    unit_free_length_mm: int
    # Net recorded-length correction on this unit (ADJUSTMENT_IN - ADJUSTMENT_OUT, never positive).
    unit_net_adjustment_mm: int
    inward_received_total_length_mm: int
    # sum(remaining + consumed + scrapped) over the inward, re-derived before commit; it equals
    # received - sum(ADJUSTMENT_OUT) + sum(ADJUSTMENT_IN).
    inward_accounted_length_mm: int
    reconciled: bool
    message: str


class CCCutResultCreate(BaseModel):
    """Record the ACTUAL result of one real CUT_CONSUME: how many good and rejected blanks came out of
    it, how many saw cuts were made and the end trim. It references an existing CUT_CONSUME ledger
    transaction (and the routing, allocation and unit that transaction belongs to, which must all
    agree) and never creates or changes a ledger row. consumed_length_mm is the operator's
    confirmation of the length that transaction consumed and must equal it exactly. Blank length and
    kerf are NOT supplied: they come from the routing. No cumulative figure is accepted."""
    model_config = ConfigDict(extra="forbid")

    routing_id: uuid.UUID
    allocation_id: uuid.UUID
    stock_unit_id: uuid.UUID
    ledger_transaction_number: RequiredText100 = Field(...)
    consumed_length_mm: PositiveMm
    actual_good_blanks: NonNegativeMm
    rejected_blanks: NonNegativeMm
    actual_cuts: NonNegativeMm
    end_trim_mm: NonNegativeMm
    remarks: Optional[str] = Field(None, max_length=2000)
    client_request_id: Optional[RequestKey] = None


class CCCutResultResult(BaseModel):
    success: bool
    replayed: bool = False
    cut_number: str
    wo_number: str
    routing_id: str
    routing_version: int
    routing_status: str
    allocation_number: str
    stock_unit_number: str
    ledger_transaction_number: str
    planned_blanks: int
    actual_good_blanks: int
    rejected_blanks: int
    actual_cuts: int
    blank_length_mm: int
    kerf_mm: int
    end_trim_mm: int
    consumed_length_mm: int
    # blanks x blank length + cuts x kerf + end trim -- the routing's own cutting formula.
    required_length_mm: int
    variance_mm: int
    reconciliation_status: str
    # Usable by the OMS gate only when RECONCILED and the routing is ACTIVE.
    usable_for_oms: bool
    # Server-derived, never client-supplied: good + rejected blanks recorded so far on this routing.
    routing_blanks_recorded: int
    routing_planned_blanks: int
    message: str


MaterialText100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class CCMaterialCreate(BaseModel):
    """Create a continuous-casting material master record. Engineering owns the technical identity: code,
    grade, section and the primary / secondary stock dimensions (whole mm)."""
    model_config = ConfigDict(extra="forbid")

    material_code: MaterialText100
    grade: MaterialText100
    section: MaterialText100
    stock_dimension_a_mm: PositiveMm
    stock_dimension_b_mm: Optional[PositiveMm] = None
    description: Optional[str] = Field(None, max_length=500)


class CCMaterialUpdate(BaseModel):
    """Update a material. Only the fields actually sent are considered (an explicit null for
    stock_dimension_b_mm or description clears it). Once an inward or a routing references the material, its
    identity (code, grade, section, dimensions) is frozen; description and is_active stay editable."""
    model_config = ConfigDict(extra="forbid")

    material_id: uuid.UUID
    material_code: Optional[MaterialText100] = None
    grade: Optional[MaterialText100] = None
    section: Optional[MaterialText100] = None
    stock_dimension_a_mm: Optional[PositiveMm] = None
    stock_dimension_b_mm: Optional[PositiveMm] = None
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class CCMaterialResult(BaseModel):
    success: bool
    material_id: str
    material_code: str
    grade: str
    section: str
    stock_dimension_a_mm: int
    stock_dimension_b_mm: Optional[int] = None
    description: Optional[str] = None
    is_active: bool
    # Whether any inward or routing refers to it (identity is then frozen).
    referenced: bool
    inward_count: int
    routing_count: int
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    message: str


class CCInwardQADecisionCreate(BaseModel):
    """Record the Quality decision on a continuous-casting inward receipt: PENDING_QA -> ACCEPTED, REJECTED or
    ON_HOLD. A reason is required for REJECTED and ON_HOLD and optional for ACCEPTED. Only a PENDING_QA inward
    can receive a decision. It is not a stock movement: no ledger row and no change to any stock unit."""
    model_config = ConfigDict(extra="forbid")

    inward_id: uuid.UUID
    decision: Literal["ACCEPTED", "REJECTED", "ON_HOLD"]
    reason: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _reason_required_unless_accepted(self):
        if self.decision in ("REJECTED", "ON_HOLD") and not (self.reason and self.reason.strip()):
            # PydanticCustomError (not ValueError): its error dict carries no exception object, so the
            # application's 422 handler can always serialise it.
            raise PydanticCustomError("reason_required", "A reason is required for a REJECTED or ON_HOLD decision.")
        return self


class CCMaterialPatch(BaseModel):
    """PATCH body for a material: exactly the fields of CCMaterialUpdate except material_id, which comes from the
    URL path. Only the fields sent are applied (an explicit null clears an optional one)."""
    model_config = ConfigDict(extra="forbid")

    material_code: Optional[MaterialText100] = None
    grade: Optional[MaterialText100] = None
    section: Optional[MaterialText100] = None
    stock_dimension_a_mm: Optional[PositiveMm] = None
    stock_dimension_b_mm: Optional[PositiveMm] = None
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class CCInwardQADecisionBody(BaseModel):
    """Request body for POST /inwards/{inward_id}/qa: CCInwardQADecisionCreate without inward_id (the URL path
    carries it). The same reason rule applies, so the full request can always be built from a valid body."""
    model_config = ConfigDict(extra="forbid")

    decision: Literal["ACCEPTED", "REJECTED", "ON_HOLD"]
    reason: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _reason_required_unless_accepted(self):
        if self.decision in ("REJECTED", "ON_HOLD") and not (self.reason and self.reason.strip()):
            raise PydanticCustomError("reason_required", "A reason is required for a REJECTED or ON_HOLD decision.")
        return self


class CCRoutingReleaseBody(BaseModel):
    """Request body for POST /routings/{routing_id}/release-superseded (the URL path carries routing_id)."""
    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = Field(None, max_length=500)


class CCInwardQADecisionResult(BaseModel):
    success: bool
    inward_id: str
    inward_number: str
    previous_qa_status: str
    qa_status: str
    reason: Optional[str] = None
    decided_by: str
    # Whether the inward's units may now be allocated (QA is one of the conditions; unit status and free
    # length remain separate, unchanged conditions).
    qa_allows_allocation: bool
    qa_block_reason: Optional[str] = None
    message: str


class CCRoutingReleaseCreate(BaseModel):
    """Release everything still reserved under a SUPERSEDED routing, one ledger row each."""
    model_config = ConfigDict(extra="forbid")

    routing_id: uuid.UUID
    reason: Optional[str] = Field(None, max_length=500)


class CCStockMovementResult(BaseModel):
    success: bool
    movement_type: str
    ledger_transaction_number: str
    allocation_id: str
    allocation_number: str
    routing_id: str
    routing_version: int
    wo_number: str
    stock_unit_number: str
    inward_number: str
    length_mm: int
    allocation_status: str
    allocation_planned_length_mm: int
    allocation_reserved_length_mm: int
    allocation_issued_length_mm: int
    allocation_consumed_length_mm: int
    unit_remaining_length_mm: int
    unit_reserved_length_mm: int
    unit_issued_length_mm: int
    unit_consumed_length_mm: int
    unit_free_length_mm: int
    # Re-derived from the ledger before commit; the operation only commits if these agree.
    ledger_reserved_length_mm: int
    reconciled: bool
    message: str


class CCRoutingReleaseResult(BaseModel):
    success: bool
    routing_id: str
    routing_version: int
    wo_number: str
    allocations_released: int
    total_released_length_mm: int
    releases: List[CCStockMovementResult]
    message: str


class CCInwardUnitOut(BaseModel):
    unit_number: str
    ledger_transaction_number: str
    original_length_mm: int
    remaining_length_mm: int


class CCInwardResult(BaseModel):
    success: bool
    inward_id: str
    inward_number: str
    material_code: str
    grn_reference: Optional[str] = None
    qa_status: str
    # Physical existence and allocation eligibility are separate answers.
    physical_stock_status: str
    allocation_eligible: bool
    allocation_ineligible_reason: Optional[str] = None
    received_piece_count: int
    received_total_length_mm: int
    # Independently re-queried from the database before commit (ledger vs units vs header).
    ledger_inward_length_mm: int
    units_original_length_mm: int
    units_remaining_length_mm: int
    reconciled: bool
    units: List[CCInwardUnitOut]
    message: str
