"""task_batches 表新增 is_demo（演示任务）列幂等迁移。

阶段十·审核准备：演示任务让未绑定团队的发音人（含微信审核员）无团队码也能
看任务、录音频、走通上传闭环；审核后由 cleanup_demo_recordings.py 清理。
ALTER 带 IF NOT EXISTS，可重复执行。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402


def main():
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE task_batches "
                "ADD COLUMN IF NOT EXISTS is_demo BOOLEAN DEFAULT FALSE"
            )
        )
    print("migrate_demo_tasks: OK")


if __name__ == "__main__":
    main()
