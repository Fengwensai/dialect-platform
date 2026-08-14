#!/usr/bin/env bash
# 方言采集平台 · 健康监控 + 自愈
#
# 由服务器 root 用户经 systemd timer（dialect-monitor.timer，每分钟）执行，
# 也可手动运行：bash monitor.sh
#
# 行为：
#   1. 每 1 分钟探 http://127.0.0.1:8000/api/health
#      （该接口会查 DB：DB 正常返回 200+db:true，DB 挂返回 503+db:false）
#   2. 首次连续失败 → 自动 systemctl restart dialect-api 一次（自愈）
#   3. 连续失败 ≥3 次 → 停止自愈，保留告警日志（提示人工排查）
#   4. 探活恢复 → 清除失败计数，恢复正常监控
#
# 日志：/var/log/dialect-monitor.log；恢复/重启/告警都会留痕。
set -uo pipefail

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
LOG_FILE="${LOG_FILE:-/var/log/dialect-monitor.log}"
STATE_FILE="${STATE_FILE:-/tmp/dialect-monitor-fails}"
MAX_FAILS="${MAX_FAILS:-3}"

log() { echo "[monitor] $(date '+%F %T') $*" >> "$LOG_FILE"; }

# 探活：HTTP 200 视为健康（health 接口 DB 挂时返回 503）
if curl -sf --max-time 10 "$HEALTH_URL" >/dev/null 2>&1; then
  if [ -f "$STATE_FILE" ]; then
    rm -f "$STATE_FILE"
    log "恢复：health 探活成功，清除失败计数，恢复正常监控"
  fi
  exit 0
fi

# 本次失败：累计连续失败次数
FAILS=0
[ -f "$STATE_FILE" ] && FAILS="$(cat "$STATE_FILE" 2>/dev/null || echo 0)"
FAILS=$((FAILS + 1))
echo "$FAILS" > "$STATE_FILE"
log "警告：health 探活失败（连续第 ${FAILS} 次）"

# 已超过自愈阈值：停止自愈，留告警，提示人工排查
if [ "$FAILS" -ge "$MAX_FAILS" ]; then
  log "告警：连续失败 ${FAILS} 次，已停止自愈。请人工排查：systemctl status dialect-api && journalctl -u dialect-api -n 100"
  exit 1
fi

# 首次失败：尝试自愈一次（重启服务），等就绪后再探一次确认
if [ "$FAILS" -eq 1 ]; then
  log "自愈：重启 dialect-api ..."
  systemctl restart dialect-api || log "错误：systemctl restart dialect-api 失败"
  # 给服务 20s 启动 + DB 连接窗口，然后再探一次
  for _ in $(seq 1 20); do
    sleep 1
    if curl -sf --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then
      rm -f "$STATE_FILE"
      log "自愈成功：重启后 health 恢复"
      exit 0
    fi
  done
  log "警告：重启 20s 后仍未恢复（连续失败 2 次），等待下一轮继续探测"
  exit 1
fi

exit 1
