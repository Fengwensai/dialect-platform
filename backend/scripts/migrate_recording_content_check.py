"""recordings 表新增内容安全列（content_check_status / media_check_trace_id）幂等迁移。

阶段十：微信 media_check_async 音频内容检测发起后回填状态与 trace_id。
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
                "ADD COLUMN IF NOT EXISTS content_check_status VARCHAR(20)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE recordings "
                "ADD COLUMN IF NOT EXISTS media_check_trace_id VARCHAR(64)"
            )
        )
    print("migrate_recording_content_check: OK")


if __name__ == "__main__":
    main()
