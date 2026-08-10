"""任务表新增 team_code（关联团队码）幂等迁移。

阶段八：任务创建时可选关联团队码（一码一区），地区由团队码带出，仅展示/追溯，
小程序端隔离仍按省+市。ALTER 均带 IF NOT EXISTS，可重复执行。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text

from app.db import engine


def main():
    with engine.begin() as conn:
        # 1. task_batches 加 team_code（VARCHAR 32，与 team_codes.code 同宽）
        conn.execute(
            text(
                "ALTER TABLE task_batches "
                "ADD COLUMN IF NOT EXISTS team_code VARCHAR(32)"
            )
        )
        # 2. 索引（按团队码筛选任务）
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_task_batches_team_code "
                "ON task_batches (team_code)"
            )
        )
    print("migrate_task_team_code: OK")


if __name__ == "__main__":
    main()
