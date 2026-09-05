import enum
import uuid
from sqlalchemy import Column, String, Boolean, Enum, DateTime
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    CEO = "ceo"
    PRODUCTION_MANAGER = "production_manager"
    PLANNER = "planner"
    QA = "qa"
    DISPATCH = "dispatch"
    MACHINE_OPERATOR = "machine_operator"
    OPERATOR = "operator"
    PACKING = "packing"
    STORE = "store"
    SALES = "sales"

class User(Base):
    __tablename__ = "users"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    employee_id = Column(String, nullable=True)
    department = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
