# 方言采集平台 · 数据备份与还原（后台完善项 8）

> 现状：生产服务器已启用**每日自动备份**（cron 每日 03:17），且已做「备份 → 还原到临时库 → 对比表数据一致」验证。
> 覆盖范围：**PostgreSQL 数据库 + 媒体文件（录音/头像）+ 配置文件快照（.env）**。

## 1. 备份范围与产物

每次备份在服务器 `/data/dialect/backups` 下生成三份文件（时间戳 `YYYYMMDD_HHMMSS`）：

| 文件 | 内容 | 说明 |
|---|---|---|
| `dialect_admin_<时间戳>.dump` | PG 全库逻辑备份 | `pg_dump -Fc` 自定义格式，**自带压缩**，可用 `pg_restore` 还原 |
| `media_<时间戳>.tar.gz` | `/data/dialect/media` 全部文件（录音 + 头像） | `tar -czf` |
| `env_<时间戳>.env` | `.env` 配置快照 | **仅 root 可读（chmod 600）**，含 JWT/微信/COS 等密钥 |

- **执行方式**：root 用户经 `/etc/cron.d/dialect-backup` 每日 `03:17` 执行 `bash /opt/dialect/backend/scripts/backup.sh`，日志追加到 `/var/log/dialect-backup.log`。
- **保留策略**：默认保留 **14 天**（`RETENTION_DAYS` 可覆盖），超期文件自动删除。
- **手动执行**：`bash /opt/dialect/backend/scripts/backup.sh`（服务器上，root）。
- 备份走 PostgreSQL **peer 认证**（`sudo -u postgres`），脚本与文档中不含任何数据库密码/密钥。

## 2. 还原步骤（灾难恢复）

前提：PostgreSQL 中需存在 `dialect` 角色（首次部署的 `create_db.sql` / `deploy.sh` 会创建；若角色丢失先执行它）。

### 2.1 先验证备份可还原（推荐，先灌临时库核对再替换）

```bash
# 服务器上，root
DUMP=$(ls -t /data/dialect/backups/dialect_admin_*.dump | head -1)   # 选最新一份
sudo -u postgres dropdb --if-exists dialect_restore_check
sudo -u postgres createdb -O dialect dialect_restore_check
sudo -u postgres pg_restore -d dialect_restore_check "$DUMP"

# 对比关键表数据量（应与线上一致；这张表 list 不是硬性清单，按需查）
for t in recordings speakers word_library task_batches admin_users regions; do
  L=$(sudo -u postgres psql -d dialect_admin -tAc "SELECT count(*) FROM $t;")
  R=$(sudo -u postgres psql -d dialect_restore_check -tAc "SELECT count(*) FROM $t;")
  echo "$t: 线上=$L 还原=$R"
done

# 确认一致后删除临时库
sudo -u postgres dropdb dialect_restore_check
```

### 2.2 正式还原（用备份替换线上库）

```bash
DUMP=$(ls -t /data/dialect/backups/dialect_admin_*.dump | head -1)

# 断开线上连接 → 删旧库 → 建空库 → 灌备份
sudo -u postgres psql -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='dialect_admin' AND pid<>pg_backend_pid();"
sudo -u postgres dropdb dialect_admin
sudo -u postgres createdb -O dialect dialect_admin
sudo -u postgres pg_restore -d dialect_admin "$DUMP"

# 重启应用，确认无报错
sudo systemctl restart dialect-api
sudo journalctl -u dialect-api -n 30
```

### 2.3 还原媒体文件

```bash
# 解包到 /data/dialect（tar 内顶层就是 media/，会还原回 /data/dialect/media）
cd /data/dialect
sudo tar -xzf /data/dialect/backups/media_<时间戳>.tar.gz
sudo chown -R www-data:www-data /data/dialect/media
```

### 2.4 还原配置快照（.env）

```bash
# 仅当 /opt/dialect/backend/.env 丢失或损坏时
sudo cp /data/dialect/backups/env_<时间戳>.env /opt/dialect/backend/.env
sudo chown www-data:www-data /opt/dialect/backend/.env
sudo chmod 600 /opt/dialect/backend/.env
sudo systemctl restart dialect-api
```

## 3. 注意与限制

- **服务器本地备份不防磁盘损坏/整机丢失**。真正的异地容灾在腾讯云 COS 启用后补：把 `/data/dialect/backups` 里的产物上传到 COS 远端（`migrate_recordings_to_cos.py` 已有 COS 客户端先例，备份脚本预留了加 hook 的位置）。
- 备份的是**逻辑数据**（可还原的 SQL/对象），不是整机镜像；重装系统后用 `deploy.sh` + 本备份即可恢复数据。
- `.env` 快照含密钥，目录 `/data/dialect/backups` 为 `700` 仅 root 可进；请勿把备份文件拷到公网。
- 修改备份配置（保留天数、目录）直接改 `backend/scripts/backup.sh` 顶部环境变量，或覆盖 `.env` 不在场时的环境变量；改脚本后需重新 `scp` 到服务器 `/opt/dialect/backend/scripts/`。
- 检查备份是否正常：`tail -5 /var/log/dialect-backup.log`（应有每日 `[backup] ... 完成` 记录）。
