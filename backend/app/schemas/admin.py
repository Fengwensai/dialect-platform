from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    name: str
    role: str
    province_code: str | None = None
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminOut


class UserCreate(BaseModel):
    username: str
    password: str = Field(min_length=6)
    name: str = ""
    role: str = "province_admin"
    province_code: str | None = None


class UserUpdate(BaseModel):
    password: str | None = None
    name: str | None = None
    role: str | None = None
    province_code: str | None = None
