"""清理演示任务数据（微信审核通过后执行）。

演示任务（is_demo）在审核期暴露给未绑定用户采集，审核后应清理演示录音，避免混入正式数据。
- 默认：删除所有演示任务下的录音（含 COS 对象/本地文件），并把演示任务关闭（可重新发布复用）。
- --hard：额外删除演示任务本身及词条关联。

用法: ./.venv/Scripts/python.exe scripts/cleanup_demo_recordings.py [--hard]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import SessionLocal  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.services import storage  # noqa: E402


def main():
    hard = "--hard" in sys.argv
    db = SessionLocal()
    try:
        demo = db.query(TaskBatch).filter(TaskBatch.is_demo.is_(True)).all()
        if not demo:
            print("cleanup_demo_recordings: 无演示任务")
            return
        rec_deleted = 0
        for t in demo:
            recs = db.query(Recording).filter(Recording.task_id == t.id).all()
            for r in recs:
                storage.delete_object(r.audio_url)  # COS 对象 / 本地文件，幂等
                db.delete(r)
                rec_deleted += 1
            if hard:
                db.query(TaskBatchItem).filter(
                    TaskBatchItem.task_batch_id == t.id
                ).delete()
                db.delete(t)
            else:
                t.status = "closed"
        db.commit()
        action = "已删除" if hard else "已关闭"
        print(
            f"cleanup_demo_recordings: 删除演示录音 {rec_deleted} 条，"
            f"演示任务{action}（{len(demo)} 个）"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
