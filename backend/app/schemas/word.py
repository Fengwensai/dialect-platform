from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    dialect_point: str
    content: str
    example_sentence: str | None = None
    remark: str | None = None
    pronunciation_hint: str | None = None
    province_code: str | None = None
    city_code: str | None = None
    district_code: str | None = None
    status: str = "active"
    created_at: datetime


class WordUpdate(BaseModel):
    code: str | None = None
    dialect_point: str | None = None
    content: str | None = None
    example_sentence: str | None = None
    remark: str | None = None
    pronunciation_hint: str | None = None
    province_code: str | None = None
    city_code: str | None = None
    district_code: str | None = None
    status: str | None = None  # active 启用 / disabled 禁用
