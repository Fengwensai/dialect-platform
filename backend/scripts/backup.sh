#!/usr/bin/env bash
# 方言采集平台 · 数据库 + 媒体 + 配置快照 每日备份
#
# 由服务器 root 用户经 cron（/etc/cron.d/dialect-backup，每日 03:17）执行，
# 也可手动运行：bash backup.sh
#
# 产物（默认目录 /data/dialect/backups，可用 BACKUP_ROOT 覆盖）：
#   dialect_admin_YYYYMMDD_HHMMSS.dump   PG 全库自定义格式 dump（自带压缩）
#   media_YYYYMMDD_HHMMSS.tar.gz         媒体文件（录音 + 头像）打包
#   env_YYYYMMDD_HHMMSS.env              .env 配置快照（chmod 600，仅 root 可读）
#
# 保留策略：默认保留 14 天（RETENTION_DAYS 可覆盖），超过的自动删除。
#
# 说明：
#   - 走 PostgreSQL peer 认证（sudo -u postgres），脚本内不出现任何数据库密码/密钥。
#   - COS 启用后，如需把备份同步到云端，可在下方「完成」前追加上传步骤
#     （migrate_recordings_to_cos.py 已有 COS 客户端先例）。
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/data/dialect/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
DB_NAME="${DB_NAME:-dialect_admin}"
MEDIA_ROOT="${MEDIA_ROOT:-/data/dialect/media}"
ENV_FILE="${ENV_FILE:-/opt/dialect/backend/.env}"
TS="$(date +%Y%m%d_%H%M%S)"

# 目录归 postgres，pg_dump 才能写入；root 后续写入不受 700 限制
install -d -o postgres -g postgres -m 700 "$BACKUP_ROOT"

echo "[backup] $(date '+%F %T') 开始：DB=$DB_NAME → $BACKUP_ROOT"

# 1) PostgreSQL 逻辑备份（自定义格式，自带压缩；peer 认证无需密码）
sudo -u postgres pg_dump -Fc "$DB_NAME" -f "$BACKUP_ROOT/${DB_NAME}_${TS}.dump"

# 2) 媒体文件打包（目录不存在则跳过）
if [ -d "$MEDIA_ROOT" ]; then
  tar -czf "$BACKUP_ROOT/media_${TS}.tar.gz" \
      -C "$(dirname "$MEDIA_ROOT")" "$(basename "$MEDIA_ROOT")"
fi

# 3) 配置快照（含 .env，仅 root 可读）
if [ -f "$ENV_FILE" ]; then
  cp "$ENV_FILE" "$BACKUP_ROOT/env_${TS}.env"
  chmod 600 "$BACKUP_ROOT/env_${TS}.env"
fi

# 4) 保留期清理（只删超过 RETENTION_DAYS 天前的，当日新建不受影响）
find "$BACKUP_ROOT" -type f -mtime +$RETENTION_DAYS \
     \( -name "${DB_NAME}_*.dump" -o -name 'media_*.tar.gz' -o -name 'env_*.env' \) -delete

# 5) 校验 dump 非空（set -e 下失败即退出非零，cron 会留痕于日志）
test -s "$BACKUP_ROOT/${DB_NAME}_${TS}.dump"

echo "[backup] $(date '+%F %T') 完成 → $BACKUP_ROOT"
ls -lh "$BACKUP_ROOT" | tail -4
