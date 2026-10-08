import enum
import re
import uuid
from sqlalchemy import Column, String, Integer, Date, Enum, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Session, relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class OrderStatus(str, enum.Enum):
    ACCEPT = "accept"
    CONFIRMED = "confirmed"
    HOLD = "hold"
    REJECT = "reject"

class Customer(Base):
    __tablename__ = "customers"
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    customer_code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    gst = Column(String, nullable=True)
    contact_person = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    orders = relationship("Order", back_populates="customer")

class Part(Base):
    __tablename__ = "parts"
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    part_number = Column(String, unique=True, nullable=False)
    grade = Column(String)
    description = Column(String)
    orders = relationship("Order", back_populates="part")


def next_internal_part_number(db: Session, customer_code: str) -> str:
    """Authoritative internal Part Number generation for a genuinely new part.

    Mirrors the real, pre-existing Part Master import convention (verified against
    the actual imported data, e.g. customer code 'PMC' -> 'PMC1' .. 'PMC380'):
    {Customer Code}{next per-customer sequential integer}, no separator. Follows
    the same collision-resistant approach as next_nc_number() -- finds the true
    highest existing suffix for this customer's parts rather than a plain
    COUNT(*)+1, which drifts out of sync once gaps exist (collapsed duplicates,
    excluded conflicts, etc. -- exactly as seen in the real imported data)."""
    prefix = customer_code.strip().upper()
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    highest = 0
    for (part_number,) in db.query(Part.part_number).filter(Part.part_number.like(f"{prefix}%")).all():
        m = pattern.match(part_number or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}{highest + 1}"

class Order(Base):
    """Represents an accepted OAR (Order Acknowledgement Record)."""
    __tablename__ = "orders"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    oar_number = Column(String, unique=True, nullable=True)
    customer_id = Column(GUID, ForeignKey("customers.id"), nullable=False)
    part_id = Column(GUID, ForeignKey("parts.id"), nullable=False)
    customer_po = Column(String, nullable=False)
    po_qty = Column(Integer, nullable=False)
    max_batch_size = Column(Integer, nullable=False)
    delivery_date = Column(Date)
    order_type = Column(String)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.ACCEPT)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Demand-source linkage. source_type defaults to "po" so every existing OAR row
    # (created before this feature existed) is correctly, automatically treated as
    # PO-sourced -- confirmed demand, exactly what it always was -- with no backfill
    # migration required. po_line_id/schedule_id/oar_po_status stay null for those
    # rows and for any new PO-sourced OAR; they are populated only for the
    # schedule-based intake and PO-matching workflow.
    source_type = Column(String, nullable=False, default="po")
    po_line_id = Column(GUID, ForeignKey("po_lines.id"), nullable=True)
    schedule_id = Column(GUID, ForeignKey("schedule_master.id"), nullable=True)
    oar_po_status = Column(String, nullable=True)

    customer = relationship("Customer", back_populates="orders")
    part = relationship("Part", back_populates="orders")
    work_orders = relationship("WorkOrder", back_populates="order")
    po_line = relationship("POLine", back_populates="orders")
    schedule = relationship("ScheduleMaster", back_populates="orders")
