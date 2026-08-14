from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RecordingOut(BaseModel):
    """上传录音的响应。"""

    recording_id: int
    audio_url: str
    status: str
    speaker_id: int | None = None
    overwritten: bool = False


class LoginRequest(BaseModel):
    """小程序 wx.login 换 token。code 必填，device_id 用于与既有录音身份统一。"""

    code: str
    device_id: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    province_code: str | None = None
    gender: str | None = None
    age_bracket: str | None = None


class ProfileUpdateRequest(BaseModel):
    """发音人自助更新资料。null/缺省=不改；空串 ""=清空（nickname 空串/缺省=不改）。

    属地（province_code/city_code）由团队码绑定决定，此处不允许自改。
    """

    gender: str | None = None
    age_bracket: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None


class SpeakerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    openid: str | None = None
    nickname: str
    avatar_url: str | None = None
    province_code: str | None = None
    city_code: str | None = None
    team_code: str | None = None
    gender: str | None = None
    age_bracket: str | None = None
    created_at: datetime


class TeamJoinRequest(BaseModel):
    """发音人凭团队码绑定属地。"""

    code: str


class MpToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    speaker: SpeakerOut
    pending_agreements: list[str] = []  # 尚未同意最新版的协议 type（空 = 全部已同意）


class MpTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    province_code: str
    city_code: str | None = None
    district_code: str | None = None
    required_audio_count: int
    status: str
    is_demo: bool = False  # 演示任务：审核/体验用，前端打标
    word_count: int = 0
    recorded_count: int = 0
    rejected_count: int = 0  # 需重录（被驳回）的去重词条数
    # 领取制（阶段十一）
    claim_limit: int = 10  # 每人领取上限
    my_claimed: int = 0  # 我当前已领取词条数
    claimable: int = 0  # 我还能领多少（=max(0,min(claim_limit-my_claimed, available))）
    available: int = 0  # 剩余未领词条数


class MpTaskSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    required_audio_count: int
    claim_limit: int = 10


class MpWordOut(BaseModel):
    word_id: int
    code: str
    content: str
    example_sentence: str | None = None
    pronunciation_hint: str | None = None
    remark: str | None = None
    mandarin_transcript: str | None = None  # 审核页填写的普通话转写（最新录音）
    dialect_transcript: str | None = None  # 审核页填写的方言转写
    recorded: bool = False
    recording_id: int | None = None
    status: str | None = None  # 该词条最新录音状态：pending/approved/rejected；未录为 None


class MpClaimStats(BaseModel):
    """领取统计（任务词条池视角，按当前发音人）。"""

    task_word_total: int = 0  # 任务词条总数（active）
    claim_limit: int = 10
    my_claimed: int = 0  # 我当前已领取条数
    claimable: int = 0  # 我还能领多少
    available: int = 0  # 剩余未领条数
    my_claim_word_ids: list[int] = []  # 我领取的词条 id


class MpClaimRequest(BaseModel):
    """领取请求：count（自动按 word_id 取前 N 条）与 word_ids（精确领取）二选一。

    两者都传时优先 word_ids；都不传 → 422。device_id 供匿名（无 token）路径建档用。
    """

    count: int | None = None
    word_ids: list[int] | None = None
    device_id: str | None = None


class MpClaimOut(BaseModel):
    """领取/退回后的响应。"""

    claimed_word_ids: list[int] = []
    stats: MpClaimStats


class MpProgressOut(BaseModel):
    task_id: int
    total_words: int
    recorded: int
    pending: int
    approved: int
    rejected: int


class MpOverallProgress(BaseModel):
    """发音人总体录音进度（跨任务按状态汇总）。"""

    recorded: int
    pending: int
    approved: int
    rejected: int


class MpDurationStats(BaseModel):
    """发音人自己的录音时长统计（全部任务，时长单位毫秒）。"""

    total_count: int = 0
    total_duration_ms: int = 0
    pending_count: int = 0
    pending_duration_ms: int = 0
    approved_count: int = 0
    approved_duration_ms: int = 0
    rejected_count: int = 0
    rejected_duration_ms: int = 0


class MpRegion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
