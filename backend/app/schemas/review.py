from datetime import datetime

from pydantic import BaseModel


class VerdictRequest(BaseModel):
    """审核判决：approved=True 通过，False 驳回；reasons 为固定原因 key 列表（可空），note 为备注。"""

    approved: bool
    reasons: list[str] | None = None
    note: str | None = None


class BatchVerdictRequest(BaseModel):
    """批量审核：对多条录音统一通过/驳回。只处理 pending，已审过的不再改动。"""

    recording_ids: list[int]
    approved: bool
    reasons: list[str] | None = None
    note: str | None = None


class BatchVerdictResult(BaseModel):
    """批量审核结果。skipped = 已审过 / 不在本省范围的条数（未改动）。"""

    processed: int
    skipped: int


class TranscriptUpdate(BaseModel):
    """更新录音转写（审核页填写）。缺省=不改；null/空串=清空。"""

    mandarin_transcript: str | None = None
    dialect_transcript: str | None = None


class ReviewRecordingOut(BaseModel):
    """审核列表/审核结果的一条录音（含富化展示字段）。"""

    id: int
    task_id: int
    task_name: str
    province_code: str | None = None
    word_id: int
    word_code: str | None = None
    word_content: str
    word_dialect_point: str | None = None
    word_example_sentence: str | None = None
    word_pronunciation_hint: str | None = None
    word_remark: str | None = None
    speaker_id: int
    speaker_nickname: str | None = None
    speaker_device: str | None = None
    speaker_gender: str | None = None
    speaker_age_bracket: str | None = None
    audio_url: str
    audio_duration: int = 0  # 毫秒
    file_size: int = 0
    # 录音质量预检（后台完善 1）：ok/suspect/unparsed + flags + metrics，旧数据为 None
    quality_status: str | None = None
    quality_flags: str | None = None
    quality_metrics: dict | None = None
    mandarin_transcript: str | None = None
    dialect_transcript: str | None = None
    status: str
    review_note: str | None = None
    reject_reasons: str | None = None  # 驳回原因 key 逗号连接（如 noise,misread）；旧数据为 None
    reviewed_by: int | None = None
    reviewed_by_name: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None
