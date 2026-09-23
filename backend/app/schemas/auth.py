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
    must_change_password: bool = False

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    email: EmailStr
    role: UserRole
    department: Optional[str] = None
    is_active: bool = True
    must_change_password: bool = False

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v):
        return str(v)

# Admin user-management: creating an account never takes a password from the caller --
# the server always generates one (see app.core.security.generate_temp_password).
class AdminUserCreate(BaseModel):
    full_name: str
    email: EmailStr
    department: Optional[str] = None
    role: UserRole

class TempPasswordResult(BaseModel):
    """The ONE-TIME response shown to the admin right after create/reset. This is the
    only place a plaintext password ever appears in any API response, and it is never
    persisted anywhere -- only its bcrypt hash is stored."""
    user: UserOut
    temporary_password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class SetActiveRequest(BaseModel):
    is_active: bool
