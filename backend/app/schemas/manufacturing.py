import uuid
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChecklistItemStatusEnum(str):
    READY = "READY"
    NOT_READY = "NOT_READY"
    N_A = "N_A"
    EXCEPTION = "EXCEPTION"


class ManufacturingKPIs(BaseModel):
    pending_review: int
    ready_for_release: int
    released: int
    blocked: int
    replacement_count: int


class MachineOption(BaseModel):
    id: str
    machine_code: str
    machine_name: str
    department: Optional[str] = None
    is_active: bool

    @field_validator("id", mode="before")
    def coerce_id_to_str(cls, v):
        return str(v) if isinstance(v, uuid.UUID) else v


class OperatorOption(BaseModel):
    id: str
    operator_code: str
    operator_name: str
    skill_level: Optional[str] = None
    is_active: bool

    @field_validator("id", mode="before")
    def coerce_id_to_str(cls, v):
        return str(v) if isinstance(v, uuid.UUID) else v


class WOManufacturingReadinessItemOut(BaseModel):
    work_order_id: str
    work_order_number: str
    part_id: str
    part_name: str
    customer_name: str
    order_type: str
    quantity: int
    target_date: Optional[str] = None
    is_replacement: bool = False
    source_wo_number: Optional[str] = None
    replacement_reason: Optional[str] = None

    # Upstream Engineering Gate status
    engineering_released: bool
    engineering_released_at: Optional[str] = None
    engineering_document_revision: Optional[str] = None

    # 6-Point Manufacturing Checklist Statuses
    material_staging_status: str
    machine_capacity_status: str
    tooling_fixtures_status: str
    cnc_program_setup_status: str
    gauges_quality_status: str
    operator_manning_status: str

    machine_code: Optional[str] = None
    operator_name: Optional[str] = None

    readiness_status: str
    is_released: bool
    released_at: Optional[str] = None
    passed_count: int
    total_count: int = 6

    @field_validator("work_order_id", "part_id", mode="before")
    def coerce_uuids(cls, v):
        return str(v) if isinstance(v, uuid.UUID) else v


class WOManufacturingReadinessDetailOut(BaseModel):
    work_order_id: str
    work_order_number: str
    part_id: str
    part_name: str
    customer_name: str
    order_type: str
    quantity: int
    target_date: Optional[str] = None
    is_replacement: bool = False
    source_wo_number: Optional[str] = None
    replacement_reason: Optional[str] = None

    # Engineering Gate
    engineering_released: bool
    engineering_released_by: Optional[str] = None
    engineering_released_at: Optional[str] = None
    engineering_document_revision: Optional[str] = None
    engineering_document_url: Optional[str] = None
    engineering_remarks: Optional[str] = None

    # 6-Point Checklist details (status + remark + identifiers)
    material_staging_status: str
    material_staging_remark: Optional[str] = None

    machine_capacity_status: str
    machine_capacity_remark: Optional[str] = None
    machine_id: Optional[str] = None
    machine_code: Optional[str] = None

    tooling_fixtures_status: str
    tooling_fixtures_remark: Optional[str] = None
    fixture_id: Optional[str] = None

    cnc_program_setup_status: str
    cnc_program_setup_remark: Optional[str] = None
    nc_program_number: Optional[str] = None
    setup_sheet_url: Optional[str] = None

    gauges_quality_status: str
    gauges_quality_remark: Optional[str] = None
    gauge_set_id: Optional[str] = None

    operator_manning_status: str
    operator_manning_remark: Optional[str] = None
    operator_id: Optional[str] = None
    operator_name: Optional[str] = None

    readiness_status: str
    remarks: Optional[str] = None

    # Document details
    document_name: Optional[str] = None
    document_url: Optional[str] = None
    document_revision: Optional[str] = None

    # Releasing info
    released_by_id: Optional[str] = None
    released_by_name: Optional[str] = None
    released_at: Optional[str] = None
    is_released: bool

    # Evaluation summary
    can_release: bool
    blocking_reasons: List[str]

    # Integrated Continuous Casting summary (if applicable)
    continuous_casting_summary: Optional[Dict[str, Any]] = None

    # Master options for selection
    available_machines: List[MachineOption] = []
    available_operators: List[OperatorOption] = []

    @field_validator(
        "work_order_id", "part_id", "machine_id", "operator_id", "released_by_id",
        mode="before"
    )
    def coerce_uuids(cls, v):
        return str(v) if isinstance(v, uuid.UUID) else v


class WOManufacturingReadinessUpdate(BaseModel):
    material_staging_status: Optional[str] = None
    material_staging_remark: Optional[str] = None

    machine_capacity_status: Optional[str] = None
    machine_capacity_remark: Optional[str] = None
    machine_id: Optional[str] = None
    machine_code: Optional[str] = None

    tooling_fixtures_status: Optional[str] = None
    tooling_fixtures_remark: Optional[str] = None
    fixture_id: Optional[str] = None

    cnc_program_setup_status: Optional[str] = None
    cnc_program_setup_remark: Optional[str] = None
    nc_program_number: Optional[str] = None
    setup_sheet_url: Optional[str] = None

    gauges_quality_status: Optional[str] = None
    gauges_quality_remark: Optional[str] = None
    gauge_set_id: Optional[str] = None

    operator_manning_status: Optional[str] = None
    operator_manning_remark: Optional[str] = None
    operator_id: Optional[str] = None
    operator_name: Optional[str] = None

    document_name: Optional[str] = None
    document_url: Optional[str] = None
    document_revision: Optional[str] = None
    remarks: Optional[str] = None


class ManufacturingReleaseRequest(BaseModel):
    document_name: Optional[str] = None
    document_url: Optional[str] = None
    document_revision: Optional[str] = None
    remarks: Optional[str] = None


class ManufacturingRevocationRequest(BaseModel):
    revocation_reason: str


class ManufacturingReleaseResponse(BaseModel):
    work_order_id: str
    work_order_number: str
    status: str
    is_released: bool
    manufacturing_released_by: Optional[str] = None
    manufacturing_released_at: Optional[str] = None
    message: str

    @field_validator("work_order_id", mode="before")
    def coerce_uuids(cls, v):
        return str(v) if isinstance(v, uuid.UUID) else v
