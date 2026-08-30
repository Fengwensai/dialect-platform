from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class TeamCode(Base):
    """团队码：一码一区县（省+市+区），发音人凭码绑定属地（阶段八）。

    code 全局唯一（统一存大写，绑定/建码时 normalize）；(province_code, city_code,
    district_code) 唯一约束保证一个区县只有一个团队码，天然隔离——一个地区的发音人
    绑到同一属地。历史团队码 district_code 为 NULL，视为市级团队（全市可见）。
    """

    __tablename__ = "team_codes"
    __table_args__ = (
        UniqueConstraint(
            "province_code", "city_code", "district_code", name="uq_team_code_region"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    province_code: Mapped[str] = mapped_column(String(16), index=True)
    city_code: Mapped[str] = mapped_column(String(16), index=True)
    district_code: Mapped[str | None] = mapped_column(String(16), index=True)
    created_by: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
