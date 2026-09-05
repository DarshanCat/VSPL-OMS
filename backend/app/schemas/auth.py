from pydantic import BaseModel, EmailStr, ConfigDict
from app.models.user import UserRole

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: UserRole

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    email: EmailStr
    role: UserRole
