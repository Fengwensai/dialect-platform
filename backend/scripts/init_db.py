"""初始化数据库：建表 + 灌入行政区划 + 种子管理员 + 三份协议 v1 + 种子团队码 HB-SJZ。

幂等，可在空库/现有库重复执行。种子三份协议与 HB-SJZ 团队码后，一次性空库即可直接跑
16 个回归脚本（verify_agreements 需要协议、verify_region_isolation / verify_task_team_code
需要 HB-SJZ）。

用法: ./.venv/Scripts/python.exe scripts/init_db.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/
sys.path.insert(0, str(Path(__file__).resolve().parent))          # scripts/（复用 migrate_agreements 的协议正文）

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.audit_log import AdminOperationLog  # noqa: E402 (注册模型)
from app.models.agreement import Agreement, SpeakerAgreement  # noqa: E402 (注册模型)
from app.models.import_log import ExcelImportLog  # noqa: E402  (注册模型)
from app.models.recording import Recording  # noqa: E402  (注册模型)
from app.models.region import Region  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402  (注册模型)
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402  (注册模型)
from app.models.team_code import TeamCode  # noqa: E402  (注册模型，含团队码表)
from app.models.word import WordLibrary  # noqa: E402
from migrate_agreements import PRIVACY_POLICY, USER_AGREEMENT, VOICE_AUTH  # noqa: E402

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


def seed_agreements():
    """三份协议 v1（幂等）：agreements/speaker_agreements 已由 init_tables 建表。

    正文复用 migrate_agreements.py 的常量，避免重复维护。
    """
    db = SessionLocal()
    try:
        if db.query(Agreement).first() is not None:
            print("[SKIP] agreements 已有数据")
            return
        for t, title, content in [
            ("user_agreement", "用户协议", USER_AGREEMENT),
            ("privacy_policy", "隐私政策", PRIVACY_POLICY),
            ("voice_auth", "声音单独授权协议", VOICE_AUTH),
        ]:
            db.add(Agreement(type=t, title=title, version=1, content=content))
        db.commit()
        print("[OK] 三份协议 v1 已种子")
    finally:
        db.close()


def seed_team_codes():
    """种子团队码 HB-SJZ（河北石家庄 13/1301，幂等）。

    回归脚本依赖它（verify_region_isolation / verify_task_team_code）；reset_business_data
    清空团队码后重跑 init_db 即可重建。
    """
    db = SessionLocal()
    try:
        if db.query(TeamCode).filter(TeamCode.code == "HB-SJZ").first() is not None:
            print("[SKIP] 种子团队码 HB-SJZ 已存在")
            return
        db.add(
            TeamCode(
                code="HB-SJZ",
                name="石家庄团队",
                province_code="13",
                city_code="1301",
            )
        )
        db.commit()
        print("[OK] 种子团队码 HB-SJZ (13/1301) 已创建")
    finally:
        db.close()


if __name__ == "__main__":
    init_tables()
    seed_regions()
    seed_admins()
    seed_agreements()
    seed_team_codes()
    print("初始化完成")
