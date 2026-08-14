# 方言采集平台 · 健康监控

三层监控：**健康检查端点（探测 DB）** → **服务器自愈（自动重启）** → **外部探活（UptimeRobot 告警）**。
本页说明各层是什么、怎么装、怎么查。部署基础见 `docs/deploy-guide.md`，日常更新见 `docs/update-workflow.md`。

---

## 1. 健康检查端点 `/api/health`

生产地址：`https://api.qlzby.com/api/health`（内网 `http://127.0.0.1:8000/api/health`）

每次请求会**探测数据库连通性**（`SELECT 1`），不是静态 ok：

| 状态 | HTTP | body |
|---|---|---|
| DB 正常 | 200 | `{"status":"ok","db":true,"version":"1"}` |
| DB 挂 | 503 | `{"status":"degraded","db":false,"version":"1"}` |

作用：
- 服务器自愈脚本（monitor.sh）据此判断是否重启服务；
- UptimeRobot 等外部探活据此触发告警（DB 挂返回 503 → 外部监控立刻红）。

验证：

```bash
curl -i https://api.qlzby.com/api/health     # 期望 200 + "db":true
```

---

## 2. 服务器自愈（systemd timer 每分钟探一次）

文件（已入库，部署到服务器）：
- `deploy/systemd/dialect-monitor.service` —— 每分钟跑一次 `monitor.sh`
- `deploy/systemd/dialect-monitor.timer` —— 定时器（`OnCalendar=*:*:00`）
- `backend/scripts/monitor.sh` —— 探活 + 自愈逻辑

**行为**（详情见脚本注释）：
1. 每 1 分钟探 `http://127.0.0.1:8000/api/health`；
2. **首次**失败 → `systemctl restart dialect-api` 自动重启一次（自愈），再探一次确认；
3. **连续失败 ≥3 次** → 停止自愈，留告警日志（提示人工 `journalctl -u dialect-api -n 100`）；
4. 探活**恢复** → 清除失败计数，恢复正常监控。

**安装**（一次性，服务器上执行）：

```bash
# 本机把单元文件 + 脚本同步到服务器（本地 Git Bash）：
scp deploy/systemd/dialect-monitor.service deploy/systemd/dialect-monitor.timer \
    backend/scripts/monitor.sh root@182.92.9.204:/tmp/
# 服务器上安装：
ssh root@182.92.9.204
mkdir -p /opt/dialect/backend/scripts
mv /tmp/monitor.sh /opt/dialect/backend/scripts/monitor.sh
chmod +x /opt/dialect/backend/scripts/monitor.sh
mv /tmp/dialect-monitor.service /tmp/dialect-monitor.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dialect-monitor.timer
```

**检查 / 排障**：

```bash
systemctl status dialect-monitor.timer        # active (running) 且 下一次触发时间正常
systemctl list-timers | grep dialect          # 确认每分钟触发
cat /var/log/dialect-monitor.log              # 监控日志：恢复 / 重启 / 告警都会留痕
tail -50 /var/log/dialect-monitor.log         # 看最近探测
```

> 定时器 `Persistent=true`：服务器重启后补跑错过的周期，不会漏探。
> 日志文件由脚本以 root 追加写，无需手动建。

---

## 3. 外部探活（UptimeRobot 告警，防止“服务器整个挂掉”）

自愈只能处理**应用/DB 挂了但系统还在**的情况；服务器宕机、断网、Nginx 挂掉时，
还需要**外部监控**来告警。推荐免费方案 **UptimeRobot**：

1. 注册 https://uptimerobot.com （免费档 50 个监控器够用）
2. Dashboard → **Add New Monitor**：
   - Monitor Type：**HTTP(s)**
   - Friendly Name：`方言采集平台 API`
   - URL：`https://api.qlzby.com/api/health`
   - Interval：`5 分钟`（默认即可）
   - **Advanced → Alert When Down, resumes from**: `200-299`（默认 200 即可）
3. **Contact / Alert Contacts**：至少加一个邮箱（监控红时发邮件）
4. 创建后状态应立即 **UP**。验证：手动 `ssh root@182.92.9.204 "sudo systemctl stop dialect-api"`，
   2 分钟内 UptimeRobot 应变 **DOWN** 并收到邮件；然后 `start` 恢复 UP。

> 可选：阿里云控制台→云监控也可以配 HTTP 探活 + 短信告警（免费额度内），比邮件更及时。

---

## 4. 备份异地副本（建议，COS 启用后补）

本地备份（`/data/dialect/backups`，每日 03:17 cron）只在本机。**建议**在 COS 启用后，
给 `backend/scripts/backup.sh` 追加一步：把当日 `*.dump` 上传到 COS 私有桶异地副本
（`migrate_recordings_to_cos.py` 已有 COS 客户端先例，可参考），实现「本机 + 云」双副本。
未启用 COS 前，至少每周把备份目录 rsync 到另一台机器 / 另一块盘。

---

## 5. 日常检查清单

- [ ] `curl -i https://api.qlzby.com/api/health` 返回 200 + `"db":true`
- [ ] `systemctl status dialect-monitor.timer` 为 active；`tail -5 /var/log/dialect-monitor.log` 无告警
- [ ] UptimeRobot 监控状态 **UP**，无未读告警邮件
- [ ] `/data/dialect/backups` 最近 dump 是昨天/今早的（`ls -lt /data/dialect/backups | head`）
