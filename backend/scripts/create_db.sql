-- 方言采集平台 - 数据库初始化
-- 用法（在 backend 目录下执行，需输入 postgres 超级用户密码）：
--   "/d/PostgreSQL/15/bin/psql.exe" -U postgres -h localhost -f scripts/create_db.sql
--
-- 应用用户密码与 backend/.env 中 DATABASE_URL 保持一致

CREATE USER dialect WITH PASSWORD 'Dialect_2026_P';
CREATE DATABASE dialect_admin OWNER dialect ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE dialect_admin TO dialect;
