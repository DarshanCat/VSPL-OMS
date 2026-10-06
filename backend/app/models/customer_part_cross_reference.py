import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class CustomerPartCrossReference(Base):
    """Authoritative Customer + Customer Part No -> Internal Part lookup mapping.

    Preserves customer-specific part resolution where the same Customer Part No
    may legitimately map to different internal parts for different customers.
    """
    __tablename__ = "customer_part_cross_references"
    __table_args__ = (
        UniqueConstraint("customer_id", "customer_part_no", name="ux_customer_part_cross_ref"),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    customer_id = Column(GUID, ForeignKey("customers.id"), nullable=False, index=True)
    customer_part_no = Column(String, nullable=False, index=True)
    part_id = Column(GUID, ForeignKey("parts.id"), nullable=False, index=True)
    source = Column(String, nullable=True)  # e.g. 'Fdata', 'Team-verified correction', 'Manual'
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String, nullable=True)

    customer = relationship("Customer")
    part = relationship("Part")
