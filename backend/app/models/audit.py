import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    user_name = Column(String, nullable=True)
    action = Column(String, nullable=False)
    entity = Column(String, nullable=False)
    entity_id = Column(String, nullable=True)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    details = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id])
