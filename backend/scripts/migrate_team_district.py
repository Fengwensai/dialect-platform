"""迁移：团队码/发音人属地下沉到区县（省市区三级）。

team_codes 表新增 district_code（区县级代码）；speakers 表新增 district_code；
唯一约束 uq_team_code_region 由 (province_code, city_code) 扩为 (province_code, city_code, district_code)。

- 历史团队码（含种子 HB-SJZ）district_code 保持 NULL，视为「市级团队」（全市可见），不回填。
- PG 中 UNIQUE 把 NULL 视为互异 → 市级团队与新区县团队可共存；应用层查重保证一区一码。

幂等，可重复执行。用法: ./.venv/Scripts/python.exe scripts/migrate_team_district.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402

STATEMENTS = [
    "ALTER TABLE team_codes ADD COLUMN IF NOT EXISTS district_code VARCHAR(16)",
    "CREATE INDEX IF NOT EXISTS ix_team_codes_district_code ON team_codes (district_code)",
    "ALTER TABLE speakers ADD COLUMN IF NOT EXISTS district_code VARCHAR(16)",
    "CREATE INDEX IF NOT EXISTS ix_speakers_district_code ON speakers (district_code)",
    "ALTER TABLE team_codes DROP CONSTRAINT IF EXISTS uq_team_code_region",
    "ALTER TABLE team_codes ADD CONSTRAINT uq_team_code_region UNIQUE (province_code, city_code, district_code)",
]


def migrate() -> None:
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
            print(f"[OK] {stmt}")
    print("迁移完成：team_codes.district_code / speakers.district_code / 唯一约束三级化")


if __name__ == "__main__":
    migrate()
