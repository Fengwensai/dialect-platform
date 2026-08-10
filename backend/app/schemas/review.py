from datetime import datetime

from pydantic import BaseModel


class VerdictRequest(BaseModel):
    """审核判决：approved=True 通过，False 驳回；note 为驳回原因（可空）。"""

    approved: bool
    note: str | None = None


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
    mandarin_transcript: str | None = None
    dialect_transcript: str | None = None
    status: str
    review_note: str | None = None
    reviewed_by: int | None = None
    reviewed_by_name: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None
