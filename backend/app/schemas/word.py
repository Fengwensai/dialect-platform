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
    occupied: bool = False  # 是否被草稿/已发布任务占用（占用制；仅 list_words 填充，其余场景默认 False）
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


class WordMergeRequest(BaseModel):
    """词条合并：keep 保留，remove 的数据并入 keep 后删除 remove。"""

    keep_word_id: int
    remove_word_id: int
