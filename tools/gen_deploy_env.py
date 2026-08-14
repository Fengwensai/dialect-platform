#!/usr/bin/env python3
"""生成生产部署 backend/.env 与 DEPLOY_SECRETS.txt。

用法（在仓库根目录）：
    python tools/gen_deploy_env.py

行为：
- 读取本地 backend/.env 中的 WECHAT_APPID / WECHAT_SECRET（保留，不打印）；
- 其余敏感项全部新生成随机值：数据库密码、JWT_SECRET、ADMIN_INIT_PASSWORD、WECHAT_MSG_TOKEN；
- 写入 deploy-bundle/backend/.env（生产配置）与 deploy-bundle/DEPLOY_SECRETS.txt（需人工记下的密钥）。

安全：脚本不 print 任何敏感值；需要的值只在 DEPLOY_SECRETS.txt 里。
"""
import re
import secrets
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOCAL_ENV = REPO / "backend" / ".env"
BUNDLE = REPO / "deploy-bundle"
OUT_ENV = BUNDLE / "backend" / ".env"
OUT_SECRETS = BUNDLE / "DEPLOY_SECRETS.txt"

DOMAIN = "qlzby.com"
API_DOMAIN = "api.qlzby.com"
ADMIN_DOMAIN = "admin.qlzby.com"


def read_local_env() -> dict:
    kv: dict = {}
    for line in LOCAL_ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z_]+)\s*=\s*(.*)$", line)
        if m:
            kv[m.group(1)] = m.group(2).strip()
    return kv


def main() -> None:
    if not LOCAL_ENV.exists():
        sys.exit(f"缺少本地 {LOCAL_ENV}")
    local = read_local_env()
    wechat_appid = local.get("WECHAT_APPID", "")
    wechat_secret = local.get("WECHAT_SECRET", "")
    if not wechat_appid or not wechat_secret:
        sys.exit("本地 .env 缺 WECHAT_APPID / WECHAT_SECRET，无法生成生产配置")

    db_pass = secrets.token_hex(16)        # 32 位十六进制
    jwt_secret = secrets.token_hex(32)     # 64 位十六进制
    admin_pass = secrets.token_urlsafe(12)
    msg_token = secrets.token_urlsafe(16)

    sep = "=" * 60  # 分隔线,独立变量,避免与相邻字面量发生拼接混淆
    secrets_info = (
        "方言采集平台 · 生产部署密钥（请妥善保存，勿外发）\n"
        + sep
        + "\n"
        + f"域名            : {DOMAIN}\n"
        + f"后台地址        : https://{ADMIN_DOMAIN}    登录账号: admin\n"
        + f"API 地址        : https://{API_DOMAIN}\n"
        + f"ADMIN_INIT_PASSWORD (后台登录密码) : {admin_pass}\n"
        + f"WECHAT_MSG_TOKEN (微信『消息推送』Token) : {msg_token}\n"
        + f"DATABASE_URL 密码 (PG dialect 用户)   : {db_pass}\n"
        + f"JWT_SECRET : {jwt_secret}\n"
        + sep
        + "\n"
        + "微信后台待配：\n"
        + f"  服务器域名 request/uploadFile/downloadFile = https://{API_DOMAIN}\n"
        + f"  消息推送 URL = https://{API_DOMAIN}/api/wechat/callback\n"
        + f"  消息推送 Token = 上面的 WECHAT_MSG_TOKEN（明文模式）\n"
    )
    BUNDLE.mkdir(parents=True, exist_ok=True)
    # 用 write_bytes 强制 LF 行尾（Windows 下 write_text 会把 \n 转成 \r\n，
    # 导致服务器上 sed 提取密码时带 \r，登录拼 JSON 报 "Invalid control character"）
    OUT_SECRETS.write_bytes(secrets_info.encode("utf-8"))

    env_content = (
        "# 方言采集平台 · 生产环境（由 gen_deploy_env.py 生成，敏感项勿手改）\n"
        f"DATABASE_URL=postgresql+psycopg://dialect:{db_pass}@localhost:5432/dialect_admin\n"
        f"JWT_SECRET={jwt_secret}\n"
        "JWT_EXPIRE_MINUTES=720\n"
        f"ADMIN_INIT_PASSWORD={admin_pass}\n"
        f"WECHAT_APPID={wechat_appid}\n"
        f"WECHAT_SECRET={wechat_secret}\n"
        f"MEDIA_PUBLIC_BASE=https://{API_DOMAIN}\n"
        f"CORS_ORIGINS=https://{ADMIN_DOMAIN}\n"
        "MAX_RECORDING_SIZE_MB=10\n"
        f"WECHAT_MSG_TOKEN={msg_token}\n"
        "# 存储：四项留空 = 本地磁盘兜底；后续上 COS 再填\n"
        "COS_SECRET_ID=\n"
        "COS_SECRET_KEY=\n"
        "COS_REGION=\n"
        "COS_BUCKET=\n"
        "MEDIA_ROOT=/data/dialect/media\n"
        "# —— 限流（默认值已够用）——\n"
        "LOGIN_FAIL_LIMIT=5\n"
        "LOGIN_FAIL_WINDOW_SECONDS=900\n"
        "LOGIN_IP_FAIL_LIMIT=20\n"
        "UPLOAD_RATE_LIMIT=60\n"
        "UPLOAD_RATE_WINDOW_SECONDS=600\n"
    )
    OUT_ENV.parent.mkdir(parents=True, exist_ok=True)
    OUT_ENV.write_bytes(env_content.encode("utf-8"))

    print(f"已生成: {OUT_ENV}")
    print(f"已生成: {OUT_SECRETS}（后台密码 + 微信消息推送 Token，务必保存）")


if __name__ == "__main__":
    main()
