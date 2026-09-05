import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class ProductionMovement(Base):
    """Immutable ledger of every physical part movement between manufacturing stages."""
    __tablename__ = "production_movements"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    movement_id = Column(String, unique=True, nullable=False, index=True)
    client_request_id = Column(String, nullable=True, index=True)
    source_type = Column(String, default="SMES_UI", nullable=False)  # "SMES_UI", "EXCEL_IMPORT", "API", "SYSTEM"
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    part_id = Column(GUID, ForeignKey("parts.id"), nullable=True)
    
    from_stage = Column(String, nullable=False)
    to_stage = Column(String, nullable=False)
    quantity_moved = Column(Integer, nullable=False)
    rejected_quantity = Column(Integer, default=0)
    
    machine_id = Column(String, nullable=True)
    operator_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    operator_name = Column(String, nullable=True)
    shift = Column(String, nullable=True)
    
    movement_date = Column(String, nullable=True)
    movement_time = Column(String, nullable=True)
    remarks = Column(String, nullable=True)
    
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    work_order = relationship("WorkOrder", back_populates="movements")
    operator = relationship("User", foreign_keys=[operator_id])
    creator = relationship("User", foreign_keys=[created_by])


class StageWIP(Base):
    """Current live stage WIP balance per Work Order aligned to OMS Flow Semantics."""
    __tablename__ = "stage_wips"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    stage = Column(String, nullable=False)
    
    ent_qty = Column(Integer, default=0)         # Total fed/entered into this stage
    ok_qty = Column(Integer, default=0)          # Total cleared good at this stage
    inproc_qty = Column(Integer, default=0)      # max(Ent - OK - Rej, 0)
    onhand_qty = Column(Integer, default=0)      # max(OK - Ent(next), 0)
    rejected_qty = Column(Integer, default=0)    # Total rejected at this stage
    
    received_qty = Column(Integer, default=0)    # Legacy compatibility alias to ent_qty
    available_wip = Column(Integer, default=0)   # Total WIP at this stage (inproc + onhand)
    moved_out_qty = Column(Integer, default=0)   # Total moved downstream
    scrapped_qty = Column(Integer, default=0)
    
    last_updated = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    work_order = relationship("WorkOrder", back_populates="stage_wips")
