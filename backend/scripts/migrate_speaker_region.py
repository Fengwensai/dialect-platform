"""迁移：发音人属地绑定（阶段八）。

speakers 表新增 city_code（市级代码）与 team_code（绑定用的团队码）；
新建 team_codes 表（一码一区：code 唯一 + (province_code, city_code) 唯一）。

幂等，可重复执行。用法: ./.venv/Scripts/python.exe scripts/migrate_speaker_region.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402

STATEMENTS = [
    "ALTER TABLE speakers ADD COLUMN IF NOT EXISTS city_code VARCHAR(16)",
    "ALTER TABLE speakers ADD COLUMN IF NOT EXISTS team_code VARCHAR(32)",
    "CREATE INDEX IF NOT EXISTS ix_speakers_city_code ON speakers (city_code)",
    "CREATE INDEX IF NOT EXISTS ix_speakers_team_code ON speakers (team_code)",
    """CREATE TABLE IF NOT EXISTS team_codes (
        id SERIAL PRIMARY KEY,
        code VARCHAR(32) NOT NULL UNIQUE,
        name VARCHAR(128) NOT NULL,
        province_code VARCHAR(16) NOT NULL,
        city_code VARCHAR(16) NOT NULL,
        created_by INTEGER,
        created_at TIMESTAMPTZ DEFAULT now(),
        CONSTRAINT uq_team_code_region UNIQUE (province_code, city_code)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_team_codes_province_code ON team_codes (province_code)",
    "CREATE INDEX IF NOT EXISTS ix_team_codes_city_code ON team_codes (city_code)",
]


def migrate() -> None:
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
            print(f"[OK] {stmt}")
    print("迁移完成：speakers.city_code / speakers.team_code / team_codes 表")


if __name__ == "__main__":
    migrate()
