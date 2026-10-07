import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class PartEngineeringRevision(Base):
    """Reusable Part Engineering Profile / Drawing Revision.
    A single Part can have multiple historical/active engineering revisions.
    """
    __tablename__ = "part_engineering_revisions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    part_id = Column(GUID, ForeignKey("parts.id"), nullable=False, index=True)
    drawing_number = Column(String(100), nullable=False)
    drawing_revision = Column(String(50), nullable=False)
    drawing_url = Column(String(1000), nullable=True)
    customer_spec_ref = Column(String(200), nullable=True)
    process_sheet_number = Column(String(100), nullable=True)
    pattern_number = Column(String(100), nullable=True)
    tooling_id = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    created_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)

    part = relationship("Part")
    created_by = relationship("User", foreign_keys=[created_by_id])

    __table_args__ = (
        UniqueConstraint("part_id", "drawing_revision", name="ux_part_engineering_revision"),
    )


class WOEngineeringReadiness(Base):
    """Order-level Engineering Readiness checklist and release link for a Work Order.
    Tracks mandatory 6-point engineering verification and feeds the authoritative
    work_orders release columns upon authorization.
    """
    __tablename__ = "wo_engineering_readiness"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False, unique=True, index=True)
    engineering_revision_id = Column(GUID, ForeignKey("part_engineering_revisions.id"), nullable=True)

    # 6-Point Mandatory Engineering Checklist
    drawing_available = Column(Boolean, nullable=False, default=False)
    drawing_revision_verified = Column(Boolean, nullable=False, default=False)
    customer_spec_verified = Column(Boolean, nullable=False, default=False)
    process_sheet_verified = Column(Boolean, nullable=False, default=False)
    pattern_ready = Column(Boolean, nullable=False, default=False)
    tooling_ready = Column(Boolean, nullable=False, default=False)

    # Specific verification attributes snapshot
    verified_revision = Column(String(50), nullable=True)
    drawing_url = Column(String(1000), nullable=True)
    pattern_number = Column(String(100), nullable=True)
    tooling_id = Column(String(100), nullable=True)

    # Status: PENDING | READY | RELEASED | BLOCKED
    readiness_status = Column(String(50), nullable=False, default="PENDING")
    remarks = Column(String, nullable=True)

    # Responsible engineer reference
    engineer_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    engineer_name = Column(String(200), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    work_order = relationship("WorkOrder", backref="engineering_readiness")
    engineering_revision = relationship("PartEngineeringRevision")
    engineer = relationship("User", foreign_keys=[engineer_id])
