"""recordings 表新增驳回原因列（reject_reasons）幂等迁移。

后台完善 2：审核驳回时勾选固定原因，多选 key 逗号连接存该列。
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
                "ALTER TABLE recordings "
                "ADD COLUMN IF NOT EXISTS reject_reasons VARCHAR(100)"
            )
        )
    print("migrate_recording_reject_reasons: OK")


if __name__ == "__main__":
    main()
