"""recordings 表新增录音质量预检列（quality_status / quality_flags / quality_metrics / quality_checked_at）幂等迁移。

后台完善 1：上传时自动检测 WAV 质量，打 ok/suspect/unparsed + 具体旗标。
ALTER 均带 IF NOT EXISTS，可重复执行。
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
                "ALTER TABLE recordings "
                "ADD COLUMN IF NOT EXISTS quality_status VARCHAR(20)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE recordings "
                "ADD COLUMN IF NOT EXISTS quality_flags VARCHAR(100)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE recordings "
                "ADD COLUMN IF NOT EXISTS quality_metrics JSON"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE recordings "
                "ADD COLUMN IF NOT EXISTS quality_checked_at TIMESTAMP WITH TIME ZONE"
            )
        )
    print("migrate_recording_quality: OK")


if __name__ == "__main__":
    main()
