from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class TaskBatch(Base):
    __tablename__ = "task_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    province_code: Mapped[str] = mapped_column(String(16), index=True)
    city_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    district_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # 关联团队码（阶段八）：创建时选团队则地区由团队码带出并记录归属；仅展示/追溯，隔离仍按省+市
    team_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    required_audio_count: Mapped[int] = mapped_column(default=30)
    # draft / published / closed
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # 演示任务（审核/体验用）：未绑定团队的发音人也能看能录，不按地区过滤；审核后清理
    is_demo: Mapped[bool] = mapped_column(default=False, index=True)
    created_by: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskBatchItem(Base):
    __tablename__ = "task_batch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_batch_id: Mapped[int] = mapped_column(index=True)
    word_id: Mapped[int] = mapped_column(index=True)
