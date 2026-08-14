"""任务词条领取制迁移（阶段十一）。

- 建 task_claims 表：UNIQUE(task_id, word_id) 一词条一人，是互斥领取的核心锁。
- task_batches 加 claim_limit 列（每人领取上限，默认 10）。
- 加固：task_batch_items 去重并加 UNIQUE(task_batch_id, word_id)，避免同词条重复入任务
  导致领取时 `INSERT ... LIMIT` 把同一 word 选两次被 ON CONFLICT 吞掉。
- 回填存量：把已存在录音的 (task_id, word_id, speaker_id) 生成 claims，保证存量数据可重录。

幂等：CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS / ADD COLUMN IF NOT EXISTS。
注意：回填按 recordings 生成，同词条多人录过只保留一人（DISTINCT + ON CONFLICT 先到先得）；
且不校验 claim_limit（可超限，祖父化），多余可后台解绑。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text

from app.db import engine


def main():
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS task_claims ("
                " id SERIAL PRIMARY KEY,"
                " task_id INTEGER NOT NULL,"
                " word_id INTEGER NOT NULL,"
                " speaker_id INTEGER NOT NULL,"
                " claimed_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_claims_task_word "
                "ON task_claims (task_id, word_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_task_claims_task_id "
                "ON task_claims (task_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_task_claims_word_id "
                "ON task_claims (word_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_task_claims_speaker_id "
                "ON task_claims (speaker_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_task_claims_task_speaker "
                "ON task_claims (task_id, speaker_id)"
            )
        )
        # 每人领取上限
        conn.execute(
            text(
                "ALTER TABLE task_batches ADD COLUMN IF NOT EXISTS "
                "claim_limit INTEGER NOT NULL DEFAULT 10"
            )
        )
        # 加固：task_batch_items 去重 + 唯一约束（防止重复词条入任务）
        conn.execute(
            text(
                "DELETE FROM task_batch_items t USING task_batch_items t2 "
                "WHERE t.id > t2.id "
                "AND t.task_batch_id = t2.task_batch_id "
                "AND t.word_id = t2.word_id"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_batch_items_batch_word "
                "ON task_batch_items (task_batch_id, word_id)"
            )
        )
        # 回填存量录音的领取
        backfilled = conn.execute(
            text(
                "INSERT INTO task_claims (task_id, word_id, speaker_id) "
                "SELECT DISTINCT task_id, word_id, speaker_id "
                "FROM recordings "
                "WHERE task_id IS NOT NULL AND word_id IS NOT NULL AND speaker_id IS NOT NULL "
                "ON CONFLICT (task_id, word_id) DO NOTHING"
            )
        )
        print(f"migrate_task_claims: OK, backfilled={backfilled.rowcount}")


if __name__ == "__main__":
    main()
