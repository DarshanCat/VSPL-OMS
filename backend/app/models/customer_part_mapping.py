import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class CustomerPartMapping(Base):
    """The authoritative Customer Part Number -> internal Part resolution.

    Every (customer, customer_part_number) a PO (or any future intake path) has
    ever referenced is recorded here exactly once, resolving to one authoritative
    internal Part -- this is what lets an operator enter a Customer Part Number
    without ever typing or choosing the internal Part Number themselves. Mirrors
    the real, pre-existing Part Master convention (Customer Code + Customer Part
    No -> Unique Internal Code) rather than inventing a new one."""
    __tablename__ = "customer_part_mappings"
    __table_args__ = (
        UniqueConstraint("customer_id", "part_id", "customer_part_number", name="ux_customer_part_mapping"),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    customer_id = Column(GUID, ForeignKey("customers.id"), nullable=False)
    part_id = Column(GUID, ForeignKey("parts.id"), nullable=False)
    customer_part_number = Column(String, nullable=False)
    # Mirrors the Part Master workbook's own "Status" column (e.g. "Active").
    status = Column(String, nullable=False, default="Active")
    # Mirrors the Part Master workbook's own "Date" column where available --
    # when this mapping was effective/created in the source system, not when
    # this row was inserted here (see created_at for that).
    source_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    customer = relationship("Customer")
    part = relationship("Part")
