import enum
import uuid
from sqlalchemy import Column, String, Integer, Enum, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class ProductionStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"

class ProductionUpdate(Base):
    __tablename__ = "production_updates"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    client_request_id = Column(String, nullable=True, index=True)
    stage = Column(String, nullable=False)
    machine = Column(String, nullable=True)
    operator_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    operator_name = Column(String, nullable=True)
    shift = Column(String, nullable=True)
    good_qty = Column(Integer, default=0)
    reject_qty = Column(Integer, default=0)
    status = Column(Enum(ProductionStatus), nullable=False)
    remarks = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    work_order = relationship("WorkOrder", back_populates="production_updates")
    operator = relationship("User")
