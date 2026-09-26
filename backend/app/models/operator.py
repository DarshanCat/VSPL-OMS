"""Operator master. Deliberately does NOT create a duplicate employee identity when the
authenticated User system already has this person -- `user_id` links to that existing
User where one exists; `employee_code`/`display_name` cover shop-floor operators who
select by name in production entry without necessarily having their own login. Never
physically delete a row that may be referenced by historical transactions; deactivate
it instead."""
import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class Operator(Base):
    __tablename__ = "operators"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    employee_code = Column(String, unique=True, nullable=True, index=True)
    display_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id])
