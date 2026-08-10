from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class WordLibrary(Base):
    __tablename__ = "word_library"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), default="", index=True)
    dialect_point: Mapped[str] = mapped_column(String(128), default="", index=True)
    content: Mapped[str] = mapped_column(String(255), index=True)
    example_sentence: Mapped[str | None] = mapped_column(String(500), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pronunciation_hint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    province_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    city_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    district_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active 启用 / disabled 禁用
    created_by: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
