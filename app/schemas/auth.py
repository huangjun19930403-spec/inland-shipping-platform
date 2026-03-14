from pydantic import BaseModel
from typing import List, Optional


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    real_name: str
    roles: List[str]


class UserInfo(BaseModel):
    id: int
    username: str
    real_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    status: int
    roles: List[str] = []

    class Config:
        from_attributes = True
