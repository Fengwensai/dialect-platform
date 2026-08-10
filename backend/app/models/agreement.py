from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

# 三类协议的稳定类型标识（唯一来源；显示名见各协议 title）
AGREEMENT_TYPES = ("user_agreement", "privacy_policy", "voice_auth")


class Agreement(Base):
    """协议版本表（阶段九）：每行 = 某协议的一个不可变版本。

    编辑协议 = 插入新版本（version 递增），旧版本不可变更。守卫按 max(version)
    判定发音人是否已同意最新版，故协议更新后发音人需重新同意。
    """

    __tablename__ = "agreements"
    __table_args__ = (
        UniqueConstraint("type", "version", name="uq_agreements_type_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SpeakerAgreement(Base):
    """发音人协议接受记录（阶段九）：每人每类记录已接受的最新版本。

    UNIQUE(speaker_id, type)：同一次/多次同意只保留一条，重复同意为幂等更新。
    """

    __tablename__ = "speaker_agreements"
    __table_args__ = (
        UniqueConstraint("speaker_id", "type", name="uq_speaker_agreements_speaker_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    speaker_id: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
