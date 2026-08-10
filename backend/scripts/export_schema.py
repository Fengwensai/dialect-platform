"""导出数据库表结构为 schema.sql（仅 DDL，不含数据）。

用法：
  python scripts/export_schema.py [输出路径]
默认输出到仓库根 docs/schema.sql（README/database.md 有引用）。

用 SQLAlchemy 反射现库生成 PostgreSQL 方言的 CREATE TABLE + 索引，
需要 DATABASE_URL（.env 或环境变量）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from dotenv import load_dotenv
load_dotenv()

from app.core.config import settings

OUT_DEFAULT = Path(__file__).resolve().parents[2] / "docs" / "schema.sql"


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DEFAULT
    engine = create_engine(settings.DATABASE_URL)
    meta = MetaData()
    meta.reflect(bind=engine)

    parts = [
        "-- 方言采集平台 · 数据库表结构（PostgreSQL 方言）",
        f"-- 由 scripts/export_schema.py 反射生成，共 {len(meta.tables)} 张表",
        "-- 仅结构，不含数据。表间为逻辑引用（未声明 FOREIGN KEY），详见 docs/database.md。",
        "",
    ]
    for table in sorted(meta.tables.values(), key=lambda t: t.name):
        ddl = str(CreateTable(table).compile(engine, dialect=postgresql.dialect()))
        parts.append(ddl + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(index).compile(engine, dialect=postgresql.dialect())) + ";")
        parts.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"OK: {len(meta.tables)} tables -> {out_path}")


if __name__ == "__main__":
    main()
