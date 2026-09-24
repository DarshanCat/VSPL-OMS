"""PO / Schedule master data and the demand-source linkage on Order (OAR).

Business distinction this preserves throughout: a PO is confirmed customer demand;
a Schedule is forecast/planned demand the customer has NOT yet released a PO for.
A schedule is never represented as a confirmed PO -- see ScheduleMaster.po_status
and Order.oar_po_status below.
"""
import enum
import uuid
from sqlalchemy import Column, String, Integer, Date, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class POStatus(str, enum.Enum):
    OPEN = "open"
    PARTIALLY_ALLOCATED = "partially_allocated"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ScheduleStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    AWAITING_PO = "awaiting_po"
    PO_RECEIVED = "po_received"
    MATCHED = "matched"
    CANCELLED = "cancelled"


class OrderSourceType(str, enum.Enum):
    PO = "po"
    SCHEDULE = "schedule"


class OARPOStatus(str, enum.Enum):
    """Only meaningful for schedule-sourced OARs. A PO-sourced OAR's oar_po_status
    stays null -- it was confirmed demand from the moment it was created, so this
    tracking concept does not apply to it."""
    AWAITING_PO = "awaiting_po"
    PO_MATCHED = "po_matched"


class POMaster(Base):
    __tablename__ = "po_master"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    po_number = Column(String, unique=True, nullable=False, index=True)
    customer_id = Column(GUID, ForeignKey("customers.id"), nullable=False)
    po_date = Column(Date, nullable=True)
    validity_date = Column(Date, nullable=True)
    status = Column(Enum(POStatus), nullable=False, default=POStatus.OPEN)
    created_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    customer = relationship("Customer")
    lines = relationship("POLine", back_populates="po", cascade="all, delete-orphan")


class POLine(Base):
    __tablename__ = "po_lines"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    po_id = Column(GUID, ForeignKey("po_master.id"), nullable=False)
    part_id = Column(GUID, ForeignKey("parts.id"), nullable=False)
    po_qty = Column(Integer, nullable=False)
    required_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    po = relationship("POMaster", back_populates="lines")
    part = relationship("Part")
    orders = relationship("Order", back_populates="po_line")


class ScheduleMaster(Base):
    __tablename__ = "schedule_master"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    schedule_number = Column(String, unique=True, nullable=False, index=True)
    customer_id = Column(GUID, ForeignKey("customers.id"), nullable=False)
    part_id = Column(GUID, ForeignKey("parts.id"), nullable=False)
    scheduled_qty = Column(Integer, nullable=False)
    required_date = Column(Date, nullable=True)
    customer_schedule_ref = Column(String, nullable=True)
    po_status = Column(Enum(ScheduleStatus), nullable=False, default=ScheduleStatus.SCHEDULED)
    created_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    customer = relationship("Customer")
    part = relationship("Part")
    orders = relationship("Order", back_populates="schedule")
