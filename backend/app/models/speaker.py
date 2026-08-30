from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Speaker(Base):
    """小程序发音人。

    过渡方案：先按 device_id（小程序本地生成的稳定 ID）识别发音人，
    openid 预留用于后续接入微信 wx.login 换 openid（两者均可空、唯一）。
    """

    __tablename__ = "speakers"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    openid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    province_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # 团队绑定（阶段八）：属地=省+市+区县，凭团队码绑定后锁定，管理员纠错才可改
    city_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    district_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    team_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)  # male/female/other
    age_bracket: Mapped[str | None] = mapped_column(String(20), nullable=True)  # under18/age18_30/age31_45/age46_60/over60
    upload_paused: Mapped[bool] = mapped_column(  # 管理员暂停该发音人上传（质量预警，后台完善 3）
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
