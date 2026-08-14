"""初始化数据库：建表 + 灌入行政区划 + 种子管理员。

用法: ./.venv/Scripts/python.exe scripts/init_db.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.agreement import Agreement, SpeakerAgreement  # noqa: E402 (注册模型)
from app.models.import_log import ExcelImportLog  # noqa: E402  (注册模型)
from app.models.recording import Recording  # noqa: E402  (注册模型)
from app.models.region import Region  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402  (注册模型)
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402  (注册模型)
from app.models.word import WordLibrary  # noqa: E402

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "pca-code.json"


def init_tables():
    Base.metadata.create_all(bind=engine)
    print("[OK] 数据表已创建")


def seed_regions():
    db = SessionLocal()
    try:
        if db.query(Region).first() is not None:
            print("[SKIP] regions 已有数据")
            return
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        for p in data:
            db.add(Region(code=p["code"], name=p["name"], level=1, parent_code=None))
            for c in p.get("children", []):
                db.add(
                    Region(code=c["code"], name=c["name"], level=2, parent_code=p["code"])
                )
                for d in c.get("children", []):
                    db.add(
                        Region(
                            code=d["code"],
                            name=d["name"],
                            level=3,
                            parent_code=c["code"],
                        )
                    )
        db.commit()
        total = db.query(Region).count()
        print(f"[OK] 行政区划灌入完成：共 {total} 条（{len(data)} 省）")
    finally:
        db.close()


def seed_admins():
    pwd = settings.ADMIN_INIT_PASSWORD
    db = SessionLocal()
    try:
        if db.query(AdminUser).filter(AdminUser.username == "admin").first():
            print("[SKIP] admin 已存在")
            return
        db.add(
            AdminUser(
                username="admin",
                password_hash=hash_password(pwd),
                name="超级管理员",
                role="super_admin",
            )
        )
        db.add(
            AdminUser(
                username="hebei_admin",
                password_hash=hash_password(pwd),
                name="河北管理员",
                role="province_admin",
                province_code="13",
            )
        )
        db.commit()
        print(f"[OK] 种子管理员已创建：admin/{pwd}（超管）、hebei_admin/{pwd}（河北省）")
    finally:
        db.close()


if __name__ == "__main__":
    init_tables()
    seed_regions()
    seed_admins()
    print("初始化完成")
