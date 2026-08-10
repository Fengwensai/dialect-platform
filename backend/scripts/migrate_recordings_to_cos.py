"""一次性回填：把存量本地 media/recordings/** 上传到腾讯云 COS。

在启用 COS 前运行（部署顺序见 docs/launch-check.md §8 或代码注释）：
1. 代码落地后先跑 6 个回归脚本（此时未配 COS，本地兜底全绿）；
2. .env 填 4 项 COS 凭据（暂不重启服务）；
3. 跑本脚本回填存量录音；
4. 重启服务进入 COS 模式。

说明：COS 启用后 storage.read_object 会走 COS，故本脚本读文件直接读本地磁盘。
用法: ./.venv/Scripts/python.exe scripts/migrate_recordings_to_cos.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.services import storage  # noqa: E402


def main() -> None:
    client = storage.get_client()
    if client is None:
        print("COS 未启用（缺凭据），跳过。请先在 .env 配置 COS_SECRET_ID/KEY/REGION/BUCKET。")
        return
    db = SessionLocal()
    try:
        recs = (
            db.query(Recording)
            .filter(Recording.audio_url.like("/media/recordings/%"))
            .all()
        )
        done = missing = 0
        for r in recs:
            rel = r.audio_url.removeprefix("/media/")
            disk = Path(settings.MEDIA_ROOT) / rel
            if not disk.is_file():
                missing += 1
                print(f"[skip] 本地文件缺失: {r.audio_url}")
                continue
            client.put_object(
                Bucket=settings.COS_BUCKET,
                Key=rel,
                Body=disk.read_bytes(),
                ContentType="audio/wav" if rel.endswith(".wav") else "audio/mpeg",
            )
            done += 1
        print(f"migrated={done} missing={missing}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
