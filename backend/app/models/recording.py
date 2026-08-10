from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Recording(Base):
    """录音记录。

    status 状态机：pending 待审核 → approved 通过 / rejected 驳回。
    同 (task_id, word_id, speaker_id) 重录时覆盖旧文件、更新本行（保持 id 稳定）。
    """

    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(index=True)
    word_id: Mapped[int] = mapped_column(index=True)
    speaker_id: Mapped[int] = mapped_column(index=True)
    audio_url: Mapped[str] = mapped_column(String(255))
    audio_duration: Mapped[int] = mapped_column(default=0)  # 毫秒
    file_size: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mandarin_transcript: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # 普通话转写（审核页填写）
    dialect_transcript: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # 方言/拼音转写（审核页填写）
    reviewed_by: Mapped[int | None] = mapped_column(nullable=True)
    # 内容安全（阶段十）：media_pending / media_passed / media_failed；trace_id 供域名期对账
    content_check_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    media_check_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
