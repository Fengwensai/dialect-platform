from datetime import datetime

from sqlalchemy import JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class ExcelImportLog(Base):
    __tablename__ = "excel_import_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(default="")
    total_rows: Mapped[int] = mapped_column(default=0)
    success_count: Mapped[int] = mapped_column(default=0)
    fail_count: Mapped[int] = mapped_column(default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    admin_id: Mapped[int | None] = mapped_column(nullable=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
