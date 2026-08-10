from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgreementCreate(BaseModel):
    """后台创建协议新版本。type 合法性在 router 校验（AGREEMENT_TYPES）。"""

    type: str
    title: str
    content: str


class AgreementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    version: int
    content: str
    updated_by: int | None = None
    updated_at: datetime


class MpAgreementOut(BaseModel):
    """小程序端协议内容（不含后台字段）。"""

    type: str
    title: str
    version: int
    content: str


class AgreementAcceptItem(BaseModel):
    type: str
    version: int


class AgreementAcceptRequest(BaseModel):
    accepted: list[AgreementAcceptItem]


class MpAcceptOut(BaseModel):
    """同意后的最新待确认列表（空 = 全部已同意）。"""

    pending_agreements: list[str]
