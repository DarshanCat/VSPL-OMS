import enum
import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class ChecklistItemStatus(str, enum.Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    N_A = "N_A"
    EXCEPTION = "EXCEPTION"


class WOManufacturingReadiness(Base):
    """Order-level Manufacturing Readiness checklist and release link for a Work Order.
    Tracks mandatory 6-point manufacturing feasibility verification (Material Staging,
    Machine Capacity, Tooling & Fixtures, CNC Program & Setup, Gauges & Quality, Operator Manning)
    with explicit item-level status (READY, NOT_READY, N_A, EXCEPTION) and remarks.
    Feeds authoritative work_orders manufacturing release columns upon authorization.
    """
    __tablename__ = "wo_manufacturing_readiness"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False, unique=True, index=True)

    # 1. Material Staging & Availability (N/A not permitted)
    material_staging_status = Column(String(50), nullable=False, default=ChecklistItemStatus.NOT_READY.value)
    material_staging_remark = Column(String(500), nullable=True)

    # 2. Machine Cell & Capacity (N/A not permitted)
    machine_capacity_status = Column(String(50), nullable=False, default=ChecklistItemStatus.NOT_READY.value)
    machine_capacity_remark = Column(String(500), nullable=True)
    machine_id = Column(GUID, ForeignKey("machines.id"), nullable=True)
    machine_code = Column(String(100), nullable=True)

    # 3. Tooling, Jigs & Fixtures (N/A permitted with remark)
    tooling_fixtures_status = Column(String(50), nullable=False, default=ChecklistItemStatus.NOT_READY.value)
    tooling_fixtures_remark = Column(String(500), nullable=True)
    fixture_id = Column(String(100), nullable=True)

    # 4. CNC Program & Setup Sheet (N/A permitted with remark)
    cnc_program_setup_status = Column(String(50), nullable=False, default=ChecklistItemStatus.NOT_READY.value)
    cnc_program_setup_remark = Column(String(500), nullable=True)
    nc_program_number = Column(String(100), nullable=True)
    setup_sheet_url = Column(String(1000), nullable=True)

    # 5. Gauges & Quality Inspection (N/A permitted with remark)
    gauges_quality_status = Column(String(50), nullable=False, default=ChecklistItemStatus.NOT_READY.value)
    gauges_quality_remark = Column(String(500), nullable=True)
    gauge_set_id = Column(String(100), nullable=True)

    # 6. Operator Manning & Assignment (N/A not permitted)
    operator_manning_status = Column(String(50), nullable=False, default=ChecklistItemStatus.NOT_READY.value)
    operator_manning_remark = Column(String(500), nullable=True)
    operator_id = Column(GUID, ForeignKey("operators.id"), nullable=True)
    operator_name = Column(String(200), nullable=True)

    # Overall Status: PENDING | READY | RELEASED | BLOCKED
    readiness_status = Column(String(50), nullable=False, default="PENDING")
    remarks = Column(String, nullable=True)

    # Document details for release
    document_name = Column(String(255), nullable=True)
    document_url = Column(String(1000), nullable=True)
    document_revision = Column(String(50), nullable=True)

    # Responsible manufacturing manager / user reference
    released_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    released_by_name = Column(String(200), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    work_order = relationship("WorkOrder", backref="manufacturing_readiness")
    machine = relationship("Machine", foreign_keys=[machine_id])
    operator = relationship("Operator", foreign_keys=[operator_id])
    released_by = relationship("User", foreign_keys=[released_by_id])
