"""清空全部业务数据，只保留：两个管理员 + 协议种子(3 份 v1) + 行政区划(3429 条)。

用法：
  python scripts/reset_business_data.py

清空（TRUNCATE ... RESTART IDENTITY，id 从 1 重新计）：
  speakers / recordings / team_codes / word_library /
  task_batches / task_batch_items / excel_import_logs / speaker_agreements

保留：
  admin_users（admin 超管 + hebei_admin 省管）——不动
  agreements（3 份 v1，登录协议守卫依赖）——不动
  regions（3429 行政区划，跑业务逻辑级联选择依赖）——不动

注意：破坏性操作，会删除全部业务数据（含录音文件对应记录），请确认后再跑。
表间为逻辑引用、无 FOREIGN KEY，TRUNCATE 安全。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv()

from app.core.config import settings

BUSINESS_TABLES = [
    "task_claims",
    "recordings",
    "task_batch_items",
    "task_batches",
    "team_codes",
    "speakers",
    "word_library",
    "excel_import_logs",
    "speaker_agreements",
]

KEEP_TABLES = ["admin_users", "agreements", "regions"]


def main() -> None:
    engine = create_engine(settings.DATABASE_URL)
    with engine.begin() as conn:
        for t in BUSINESS_TABLES:
            conn.execute(text(f"TRUNCATE TABLE {t} RESTART IDENTITY"))
        # 双保险：确认两个管理员都在（种子由 init_db.py 保证，这里只校验不增删）
        admins = conn.execute(text("SELECT username, role FROM admin_users ORDER BY id")).fetchall()
        print("admin_users kept:", [(a.username, a.role) for a in admins])
        for t in KEEP_TABLES:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"kept {t}: {n}")
        print("cleared:", ", ".join(BUSINESS_TABLES))


if __name__ == "__main__":
    main()
