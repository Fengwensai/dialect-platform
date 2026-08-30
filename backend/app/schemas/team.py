from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TeamCodeCreate(BaseModel):
    """创建团队码。code 存大写；一码一区县（province+city+district 唯一），三级必选。"""

    code: str
    name: str
    province_code: str
    city_code: str
    district_code: str


class TeamCodeUpdate(BaseModel):
    """团队码仅可改名。改区域/改码会让已绑定发音人失联，需要删建。"""

    name: str | None = None


class TeamCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    province_code: str
    city_code: str
    district_code: str | None = None
    created_by: int | None = None
    created_at: datetime
