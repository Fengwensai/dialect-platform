"""speakers 表新增上传暂停列（upload_paused）幂等迁移。

后台完善 3：发音人质量预警——管理员可一键暂停/恢复某发音人上传。
ALTER 带 IF NOT EXISTS，可重复执行。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text

from app.db import engine


def main():
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE speakers "
                "ADD COLUMN IF NOT EXISTS upload_paused BOOLEAN NOT NULL DEFAULT false"
            )
        )
    print("migrate_speaker_quality_warn: OK")


if __name__ == "__main__":
    main()
