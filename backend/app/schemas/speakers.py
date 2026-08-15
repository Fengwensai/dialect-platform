from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SpeakerUpdate(BaseModel):
    """后台编辑发音人画像/属地。缺省=不改；null/空串=清空。

    province_code/city_code 用于管理员纠错属地；改动会清空 team_code（原绑定作废）。
    """

    gender: str | None = None
    age_bracket: str | None = None
    province_code: str | None = None
    city_code: str | None = None
    upload_paused: bool | None = None  # 质量预警：管理员一键暂停/恢复上传（缺省不改）


class SpeakerMergeRequest(BaseModel):
    """发音人合并：keep 保留，remove 的数据并入 keep 后删除 remove（含设备/微信身份）。"""

    keep_speaker_id: int
    remove_speaker_id: int


class SpeakerTaskStat(BaseModel):
    """发音人在某个任务的录音数。"""

    task_id: int
    task_name: str
    count: int


class SpeakerRecordingStats(BaseModel):
    """发音人录音贡献统计（全量，不受列表筛选影响）。"""

    total: int
    pending: int
    approved: int
    rejected: int
    total_duration_ms: int
    approved_duration_ms: int = 0  # 有效时长：审核通过的录音总时长（毫秒）
    rejected_duration_ms: int = 0  # 无效时长：被驳回的录音总时长（毫秒）
    tasks: list[SpeakerTaskStat]


class SpeakerRecordingOut(BaseModel):
    """发音人单条录音（明细列表项）。"""

    id: int
    task_id: int
    task_name: str
    word_id: int
    word_code: str | None = None
    word_content: str
    status: str
    audio_url: str
    audio_duration: int = 0  # 毫秒
    file_size: int = 0
    review_note: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class SpeakerRecordingsOut(BaseModel):
    """发音人录音明细：分页列表 + 贡献统计。"""

    speaker_id: int
    total: int
    items: list[SpeakerRecordingOut]
    stats: SpeakerRecordingStats


class SpeakerAdminOut(BaseModel):
    """后台发音人列表项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    openid: str | None = None
    device_id: str | None = None
    nickname: str
    province_code: str | None = None
    city_code: str | None = None
    team_code: str | None = None
    gender: str | None = None
    age_bracket: str | None = None
    recording_count: int = 0
    # —— 质量预警（后台完善 3）——
    upload_paused: bool = False  # 管理员暂停上传
    approval_rate: float = 0.0  # 已审核通过率 approved/(approved+rejected)
    reviewed_total: int = 0  # 已审核条数（通过+驳回）
    quality_warned: bool = False  # 通过率低且已审核 ≥ 下限 → 标黄预警
    created_at: datetime
