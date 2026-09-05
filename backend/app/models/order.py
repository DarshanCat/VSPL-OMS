import enum
import uuid
from sqlalchemy import Column, String, Integer, Date, Enum, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class OrderStatus(str, enum.Enum):
    ACCEPT = "accept"
    HOLD = "hold"
    REJECT = "reject"

class Customer(Base):
    __tablename__ = "customers"
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    customer_code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    orders = relationship("Order", back_populates="customer")

class Part(Base):
    __tablename__ = "parts"
    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    part_number = Column(String, unique=True, nullable=False)
    grade = Column(String)
    description = Column(String)
    orders = relationship("Order", back_populates="part")

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

    customer = relationship("Customer", back_populates="orders")
    part = relationship("Part", back_populates="orders")
    work_orders = relationship("WorkOrder", back_populates="order")
