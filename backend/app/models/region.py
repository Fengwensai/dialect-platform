from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Region(Base):
    __tablename__ = "regions"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)  # adcode
    name: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[int] = mapped_column()  # 1省 2市 3区/县
    parent_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
