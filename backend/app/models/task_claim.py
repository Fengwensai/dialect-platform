from datetime import datetime

from sqlalchemy import DateTime, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class TaskClaim(Base):
    """任务词条领取（领取制，阶段十一）：每条词条只能被一个发音人领取，领取后该词条归其专有。

    互斥核心：UNIQUE(task_id, word_id)——一词条一人，其他人不能领/不能录。
    领取 = 占池；录制后该 claim 与录音绑定（已录不可自退/解绑）；未录可自退退回池子。
    """

    __tablename__ = "task_claims"
    __table_args__ = (
        UniqueConstraint("task_id", "word_id", name="uq_task_claims_task_word"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    word_id: Mapped[int] = mapped_column(Integer, index=True)
    speaker_id: Mapped[int] = mapped_column(Integer, index=True)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
