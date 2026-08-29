"""合规整改：清空存量发音人头像（微信违规通知「违规收集用户头像昵称」整改）。

隐私指引已声明「头像仅缓存于本地、不存储于服务器」，本次整改把代码对齐声明后，
存量已上传到服务器的头像即为「违规内容」，需清理：
  1) 删除 MEDIA_ROOT/avatars/ 下所有头像文件
  2) 清空所有 speakers.avatar_url（昵称保留——后台科研识别用）

默认 dry-run 仅预览；确认无误后加 --execute 真正执行。

用法:
  ./.venv/Scripts/python.exe scripts/cleanup_avatars.py            # 预览
  ./.venv/Scripts/python.exe scripts/cleanup_avatars.py --execute  # 执行
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402

EXECUTE = "--execute" in sys.argv


def main() -> None:
    avatars_dir = Path(settings.MEDIA_ROOT) / "avatars"
    files = [p for p in avatars_dir.iterdir() if p.is_file()] if avatars_dir.is_dir() else []

    db = SessionLocal()
    try:
        speakers = db.query(Speaker).filter(Speaker.avatar_url.isnot(None)).all()
    finally:
        db.close()

    print(f"头像目录: {avatars_dir}")
    print(f"  待删除头像文件: {len(files)}")
    print(f"  待清空 avatar_url 的发音人: {len(speakers)}（昵称保留）")

    if not EXECUTE:
        print("\n[dry-run] 未执行。确认后加 --execute 真正清理。")
        return

    removed = 0
    for p in files:
        try:
            p.unlink()
            removed += 1
        except OSError as e:
            print(f"  [warn] 删除失败 {p.name}: {e}")

    db = SessionLocal()
    try:
        for sp in db.query(Speaker).filter(Speaker.avatar_url.isnot(None)).all():
            sp.avatar_url = None
        db.commit()
    finally:
        db.close()

    print(f"\n完成：已删除 {removed}/{len(files)} 个头像文件，已清空 {len(speakers)} 个发音人的 avatar_url。")


if __name__ == "__main__":
    main()
