from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class AdminOperationLog(Base):
    """管理后台操作审计日志：谁、何时、做了什么（破坏性/管理类操作）。"""

    __tablename__ = "admin_operation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(nullable=True)
    # 冗余快照，防止管理员被删除后日志失联
    admin_name: Mapped[str] = mapped_column(String(64), default="")
    # 中文动词，如「删除发音人」「审核驳回」
    action: Mapped[str] = mapped_column(String(32), index=True)
    # speaker / word / task / recording / admin / team_code / import
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 人类可读摘要，如 录音 #12「词条」已驳回
    summary: Mapped[str] = mapped_column(String(512), default="")
    # 结构化信息（批量计数、迁移计数等）
    detail: Mapped[list] = mapped_column(JSON, default=list)
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
