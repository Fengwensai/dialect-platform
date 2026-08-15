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


class WorkloadReason(BaseModel):
    """驳回原因分布一行（按审核员）：key 为 reason key（unknown=未标注），label 中文，count 计数。"""

    key: str
    label: str
    count: int


class WorkloadRow(BaseModel):
    """审核员工作量/质量一行（近 days 天窗口内按 reviewed_by 聚合）。"""

    admin_id: int
    admin_name: str
    total: int  # 窗口内审核过的录音数（approved + rejected，按 reviewed_at 归属）
    approved: int
    rejected: int
    approval_rate: float  # approved / (approved + rejected)
    reasons: list[WorkloadReason]  # 驳回原因分布（按 count 降序；未标注计入 unknown）


class AuditWorkloadOut(BaseModel):
    """审核工作量报表（后台完善 9，纯派生自 recordings，无迁移）。"""

    items: list[WorkloadRow]  # 按 total 降序
    total: int  # 有审核记录的管理员数
    days: int  # 窗口天数（滚动窗口，当日=1）
