"""回填存量录音质量标记（后台完善 1）。

对 recordings 中 quality_status IS NULL 的录音，用 storage.read_object 读字节 →
analyze_audio_quality + classify → 更新 4 列。幂等（按 IS NULL 过滤，可重跑）。

服务端手动执行一次（Deploy workflow 不负责回填）：
    cd /opt/dialect/backend && .venv/bin/python scripts/backfill_recording_quality.py
可选：
    --limit 500   分批处理（默认 0=全部）
    --status ""   回填全部状态（默认仅 pending，已审过的无需打标）
"""
import sys
import os
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import SessionLocal
from app.models.recording import Recording
from app.services import storage
from app.services.audio_quality import analyze_audio_quality, classify


def main():
    parser = argparse.ArgumentParser(description="回填存量录音质量标记")
    parser.add_argument("--limit", type=int, default=0, help="最多处理条数，0=全部")
    parser.add_argument("--status", default="pending", help="回填的录音状态（空=全部，默认 pending）")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Recording).filter(Recording.quality_status.is_(None))
        if args.status:
            q = q.filter(Recording.status == args.status)
        q = q.order_by(Recording.id)
        if args.limit and args.limit > 0:
            q = q.limit(args.limit)
        recs = q.all()

        done = 0
        unparsed = 0
        failed = 0
        now = datetime.now(timezone.utc)
        for rec in recs:
            content = storage.read_object(rec.audio_url)
            if not content:
                # 读不到文件（COS/本地均缺）：标 unparsed，明确"未检测"
                failed += 1
                rec.quality_status = "unparsed"
            else:
                qc = analyze_audio_quality(content)
                if qc is None:
                    unparsed += 1
                    rec.quality_status = "unparsed"
                else:
                    q_status, q_flags = classify(qc)
                    rec.quality_status = q_status
                    rec.quality_flags = ",".join(q_flags) if q_flags else None
                    rec.quality_metrics = qc
            rec.quality_checked_at = now
            done += 1
        db.commit()
        print(
            f"backfill_recording_quality: OK 处理={done}"
            f"（读失败={failed}，unparsed={unparsed}）"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
