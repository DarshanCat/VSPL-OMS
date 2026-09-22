from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator
from app.models.user import UserRole

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: UserRole
    department: Optional[str] = None
    is_active: bool = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    email: EmailStr
    role: UserRole
    department: Optional[str] = None
    is_active: bool = True

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v):
        return str(v)
