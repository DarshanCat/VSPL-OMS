import enum
import uuid
from sqlalchemy import Column, String, Integer, Enum, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class StageCode(str, enum.Enum):
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"
    SP = "SP"
    FI = "FI"
    PACKING = "PACKING"
    BSR = "BSR"
    DISPATCH = "DISPATCH"

class WOStatus(str, enum.Enum):
    PLANNED = "planned"
    RELEASED = "released"
    IN_PRODUCTION = "in_production"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OVERDUE = "overdue"
    READY = "ready"
    DISPATCHED = "dispatched"
    CLOSED = "closed"

class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    wo_number = Column(String, unique=True, nullable=False, index=True)
    order_id = Column(GUID, ForeignKey("orders.id"), nullable=False)
    physical_wo_qty = Column(Integer, nullable=False)
    current_stage = Column(String, default="F1")
    projected_final_good = Column(Integer, default=0)
    shortfall = Column(String, default="No")  # "YES" | "No"
    status = Column(Enum(WOStatus), nullable=False, default=WOStatus.IN_PRODUCTION)
    released_by = Column(String, nullable=True)
    release_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    order = relationship("Order", back_populates="work_orders")
    routes = relationship("WORoute", back_populates="work_order", cascade="all, delete-orphan", order_by="WORoute.sequence")
    stage_wips = relationship("StageWIP", back_populates="work_order", cascade="all, delete-orphan")
    movements = relationship("ProductionMovement", back_populates="work_order", cascade="all, delete-orphan")
    packing_records = relationship("PackingRecord", back_populates="work_order", cascade="all, delete-orphan")
    production_updates = relationship("ProductionUpdate", back_populates="work_order")
    nc_records = relationship("NCRecord", back_populates="work_order")
    dispatches = relationship("Dispatch", back_populates="work_order")

class WORoute(Base):
    """Ordered stage sequence + per-stage target for a WO (back-calculated from yield)."""
    __tablename__ = "wo_routes"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    stage = Column(String, nullable=False)
    sequence = Column(Integer, nullable=False)
    stage_target_qty = Column(Integer, nullable=False)
    
    cumulative_ent_qty = Column(Integer, default=0)
    cumulative_ok_qty = Column(Integer, default=0)
    cumulative_rej_qty = Column(Integer, default=0)
    cumulative_inproc_qty = Column(Integer, default=0)
    cumulative_onhand_qty = Column(Integer, default=0)
    stage_status = Column(String, default="Pending")  # "Pending", "In-Progress", "Green", "Amber", "Red", "Skip", "Completed"

    work_order = relationship("WorkOrder", back_populates="routes")
