"""迁移：recordings 表新增转写字段（普通话/方言），幂等，可重复执行。

用法: ./.venv/Scripts/python.exe scripts/migrate_recordings_transcripts.py

无 alembic：Base.metadata.create_all 不会改现有表，存量库需一次性
ALTER TABLE ... ADD COLUMN IF NOT EXISTS 补齐新列（新增库 create_all 已含）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402

STATEMENTS = [
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS mandarin_transcript VARCHAR(1000)",
    "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS dialect_transcript VARCHAR(1000)",
]


def migrate() -> None:
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
            print(f"[OK] {stmt}")
    print("迁移完成：recordings.mandarin_transcript / recordings.dialect_transcript")


if __name__ == "__main__":
    migrate()
