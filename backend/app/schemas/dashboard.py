from datetime import datetime

from pydantic import BaseModel


class RegionBreakdownItem(BaseModel):
    """区域分布：省/市 → 发音人数 / 录音数（超管按省、省管理员按本省市级）。"""

    code: str
    name: str
    speaker_total: int
    recording_total: int


class DashboardSummary(BaseModel):
    """平台/本省概览（省管理员自动钳制为本省）。"""

    speaker_total: int
    recording_total: int
    pending: int
    approved: int
    rejected: int
    total_duration_ms: int
    approved_duration_ms: int  # 有效时长：已通过录音总时长（毫秒）
    approval_rate: float  # approved / max(approved + rejected, 1)
    active_task_total: int  # published 任务数
    team_total: int  # 发音人中 distinct 团队码数
    distinct_word_total: int  # 已录的不同词条数
    region_breakdown: list[RegionBreakdownItem]


class DashboardSpeakerRow(BaseModel):
    """看板发音人数据行（每人一行：画像 + 录音/审核/时长/活跃汇总）。"""

    id: int
    openid: str | None = None
    device_id: str | None = None
    nickname: str
    province_code: str | None = None
    city_code: str | None = None
    team_code: str | None = None
    gender: str | None = None
    age_bracket: str | None = None
    created_at: datetime
    recording_total: int = 0
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    total_duration_ms: int = 0
    approved_duration_ms: int = 0
    approval_rate: float = 0.0
    task_count: int = 0  # 参与的不同任务数
    word_count: int = 0  # 已录的不同词条数
    last_active_at: datetime | None = None


class DashboardClaimOut(BaseModel):
    """发音人领取记录（词条 + 任务 + 是否已录）。"""

    claim_id: int
    task_id: int
    task_name: str
    word_id: int
    word_code: str | None = None
    word_content: str
    recorded: bool = False  # 该词条是否已有录音
    claimed_at: datetime


class DashboardTrends(BaseModel):
    """近 days 天录音趋势（数字卡片）。"""

    days: int
    new_recordings: int  # 窗口内新增录音总数
    pending: int
    approved: int
    rejected: int
    approval_rate: float  # 窗口内通过率 approved / (approved + rejected)


class DashboardWordDifficulty(BaseModel):
    """词条采集难度（当前状态快照）：该词条各状态录音数 + 通过/驳回率。"""

    word_id: int
    code: str
    content: str
    dialect_point: str
    province_code: str | None = None
    recording_total: int = 0
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    approval_rate: float = 0.0  # approved / (approved + rejected)
    reject_rate: float = 0.0  # rejected / (approved + rejected)


class RejectionReasonRow(BaseModel):
    """驳回原因分布一行：reason 为 key（unknown=未标注），label 为中文，count 为驳回录音数。"""

    reason: str
    label: str
    count: int


class DashboardRejectionReasons(BaseModel):
    """驳回原因分布（省管理员自动钳制为本省）。total = 分布范围内驳回录音总数。"""

    total: int
    items: list[RejectionReasonRow]
