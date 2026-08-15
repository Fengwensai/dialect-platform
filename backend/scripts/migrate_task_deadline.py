"""task_batches 表新增 deadline_at（任务截止时间）列幂等迁移。

后台完善 9：可选截止时间；已发布任务过截止 → 列表/看板标「已截止」，
超管/省管可一键清理到期任务（自动关闭）。列可空，存量任务不设截止。
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
                "ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMPTZ"
            )
        )
    print("migrate_task_deadline: OK")


if __name__ == "__main__":
    main()
