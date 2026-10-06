import uuid
from sqlalchemy import Column, String, Integer, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class Heat(Base):
    """Authoritative furnace melt / heat batch record for metallurgy traceability."""
    __tablename__ = "heats"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    heat_number = Column(String, unique=True, nullable=False, index=True)
    grade = Column(String, nullable=False)
    melt_date = Column(Date, nullable=True)
    status = Column(String, nullable=False, default="ACTIVE")  # "ACTIVE", "DEPLETED", "QUARANTINED"
    tc_number = Column(String, nullable=True)  # Test Certificate / Lab Report #
    supplier_or_foundry = Column(String, nullable=True)
    remarks = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    allocations = relationship("WorkOrderHeatAllocation", back_populates="heat")


class WorkOrderHeatAllocation(Base):
    """Immutable traceability ledger of raw material / heat batch allocation to a Work Order."""
    __tablename__ = "wo_heat_allocations"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False, index=True)
    heat_id = Column(GUID, ForeignKey("heats.id"), nullable=False, index=True)
    allocated_qty = Column(Integer, nullable=False)
    stage = Column(String, nullable=False, default="F1")
    production_update_id = Column(GUID, ForeignKey("production_updates.id"), nullable=True, index=True)
    allocated_at = Column(DateTime(timezone=True), server_default=func.now())
    allocated_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    remarks = Column(String, nullable=True)

    work_order = relationship("WorkOrder", back_populates="heat_allocations")
    heat = relationship("Heat", back_populates="allocations")
    allocator = relationship("User")
    production_update = relationship("ProductionUpdate")
