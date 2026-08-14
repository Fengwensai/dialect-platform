from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    admin_id: int | None
    admin_name: str
    action: str
    target_type: str
    target_id: str | None
    summary: str
    detail: dict | list  # 结构化信息：批量/导入为 dict，管理员字段为 list
    ip: str
    created_at: datetime
