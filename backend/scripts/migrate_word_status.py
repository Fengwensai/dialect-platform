"""迁移：word_library 表新增 status 字段（active 启用 / disabled 禁用），幂等，可重复执行。

用法: ./.venv/Scripts/python.exe scripts/migrate_word_status.py

无 alembic：Base.metadata.create_all 不会改现有表，存量库需一次性
ALTER TABLE ... ADD COLUMN IF NOT EXISTS 补齐新列（新增库 create_all 已含）。
存量词条默认 active（启用）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402

STATEMENTS = [
    "ALTER TABLE word_library ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'",
    "CREATE INDEX IF NOT EXISTS ix_word_library_status ON word_library (status)",
]


def migrate() -> None:
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
            print(f"[OK] {stmt}")
    print("迁移完成：word_library.status（存量默认 active）")


if __name__ == "__main__":
    migrate()
