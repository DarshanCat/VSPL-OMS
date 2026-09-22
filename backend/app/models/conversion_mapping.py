import uuid
from sqlalchemy import Column, String, Boolean, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class ConversionPartMapping(Base):
    """The authoritative business-controlled master of which source part is allowed to
    convert into which destination part. No row here is invented by this application --
    every mapping must be created by an authorized planner/admin through the Conversion
    Mapping admin screen. Nothing converts unless an ACTIVE row exists for that exact
    (source_part, destination_part) pair, including source == destination (same-part
    conversion is never auto-allowed just because the parts match)."""
    __tablename__ = "conversion_part_mappings"
    __table_args__ = (
        UniqueConstraint("source_part_id", "destination_part_id", name="ux_conversion_mapping_pair"),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    source_part_id = Column(GUID, ForeignKey("parts.id"), nullable=False)
    destination_part_id = Column(GUID, ForeignKey("parts.id"), nullable=False)
    # PART_TO_PART | SAME_PART
    conversion_type = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    # Only populated if a specific business conversion ratio is required; most
    # part-to-part dispositions carry the quantity across unchanged (factor 1.0 implied
    # by NULL), matching the existing Conversion/RejectionDisposition quantity model.
    conversion_factor = Column(Float, nullable=True)
    created_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    updated_by_name = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    source_part = relationship("Part", foreign_keys=[source_part_id])
    destination_part = relationship("Part", foreign_keys=[destination_part_id])
