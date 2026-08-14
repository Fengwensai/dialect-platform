from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TaskBatchCreate(BaseModel):
    name: str
    description: str | None = None
    province_code: str
    city_code: str | None = None
    district_code: str | None = None
    # 阶段八：可选关联团队码，地区由团队码带出（传 team_code 时 province/city 需与之一致）
    team_code: str | None = None
    required_audio_count: int = 30
    # 每人领取上限（领取制）：单发音人同时最多领取词条数
    claim_limit: int = 10
    word_ids: list[int] = []
    # 演示任务（审核/体验用）：未绑定团队用户可见可录，不按地区过滤。仅超管可建。
    is_demo: bool = False


class TaskBatchUpdate(BaseModel):
    """编辑草稿任务。缺省=不改；word_ids 提供则整体替换词条集合。"""

    name: str | None = None
    description: str | None = None
    required_audio_count: int | None = None
    claim_limit: int | None = None
    word_ids: list[int] | None = None
    team_code: str | None = None


class TaskBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    province_code: str
    city_code: str | None = None
    district_code: str | None = None
    team_code: str | None = None
    required_audio_count: int
    claim_limit: int = 10
    status: str
    is_demo: bool = False
    created_by: int | None = None
    created_at: datetime
    published_at: datetime | None = None
    word_count: int = 0


class TaskClaimAdminOut(BaseModel):
    """管理端领取记录列表项（领取制）。"""

    claim_id: int
    word_id: int
    content: str = ""
    speaker_id: int
    nickname: str = ""
    recorded: bool = False  # 该词条是否已有录音（已录不可解绑）
    claimed_at: datetime
