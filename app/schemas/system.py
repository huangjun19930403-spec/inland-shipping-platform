from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class UserCreate(BaseModel):
    username: str
    real_name: str
    password: str
    phone: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    role_ids: List[int] = []


class UserUpdate(BaseModel):
    real_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    role_ids: Optional[List[int]] = None


class UserResponse(BaseModel):
    id: int
    username: str
    real_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    status: int
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    roles: List[str] = []

    class Config:
        from_attributes = True


class RoleResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    status: int
    sort_order: int

    class Config:
        from_attributes = True


class PasswordResetRequest(BaseModel):
    new_password: str
