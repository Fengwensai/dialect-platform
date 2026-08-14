from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend 目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_EXPIRE_MINUTES: int = 720
    # 种子管理员初始密码（init_db.py 建 admin/hebei_admin 用）。默认 admin123 便于本地联调，
    # 上线务必在 .env 设强密码再跑 init_db.py（后台无改密接口）。
    ADMIN_INIT_PASSWORD: str = "admin123"
    # 录音等媒体文件根目录（默认 backend/media，可通过 .env 的 MEDIA_ROOT 覆盖）
    MEDIA_ROOT: str = str(BASE_DIR / "media")
    # 微信小程序凭据（小程序端 AppID/Secret）。未配 Secret 时登录接口走开发兜底，
    # 把 code 直接映射为测试 openid，便于无网/无凭据联调。
    WECHAT_APPID: str | None = None
    WECHAT_SECRET: str | None = None
    # 内容安全 / CORS / 媒体公网地址（上线准备，开发默认放开/跳过）
    # CORS_ORIGINS：逗号分隔白名单；默认 * 便于本地联调，上线在 .env 收紧。
    CORS_ORIGINS: str = "*"
    # 录音文件大小上限（MB），与微信 media_check_async 的 10MB 上限对齐。
    MAX_RECORDING_SIZE_MB: int = 10
    # 公网域名前缀（如 https://api.example.com）。空 = 未上线，跳过录音异步内容检测。
    MEDIA_PUBLIC_BASE: str = ""
    # 微信「消息推送」验签 Token（mp 后台 开发→开发设置→消息推送 配置，与后台保持一致，
    # 明文模式）。空 = 跳过验签（本地联调），上线务必配置。
    WECHAT_MSG_TOKEN: str = ""
    # 腾讯云 COS（录音对象存储）：私有桶 + 预签名 URL，服务器中转。
    # 四项全填才启用 COS；任一项为空则录音落本地磁盘（MEDIA_ROOT）兜底。
    # COS_BUCKET 形如 "桶名-appid"（必须含 APPID 后缀）；COS_REGION 如 "ap-beijing"。
    COS_SECRET_ID: str = ""
    COS_SECRET_KEY: str = ""
    COS_REGION: str = ""
    COS_BUCKET: str = ""
    # —— 限流（进程内固定窗口；上线可调，防爆破/防刷）——
    # 登录防爆破：连续 LOGIN_FAIL_LIMIT 次失败后锁定 LOGIN_FAIL_WINDOW_SECONDS 秒；
    # 按账号与按 IP 各计一份，成功登录即清零（正常用户不会误锁）。
    LOGIN_FAIL_LIMIT: int = 5
    LOGIN_FAIL_WINDOW_SECONDS: int = 900
    LOGIN_IP_FAIL_LIMIT: int = 20
    # 登录速率节流：每 IP 每窗口最多 LOGIN_ATTEMPT_LIMIT 次尝试（无论成败），
    # 在失败锁定之外按总流量限次，进一步压暴力破解（成功登录也计数）。
    LOGIN_ATTEMPT_LIMIT: int = 30
    LOGIN_ATTEMPT_WINDOW_SECONDS: int = 300
    # 上传频率：单个发音人 UPLOAD_RATE_LIMIT 次 / UPLOAD_RATE_WINDOW_SECONDS 秒
    UPLOAD_RATE_LIMIT: int = 60
    UPLOAD_RATE_WINDOW_SECONDS: int = 600

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
    )


settings = Settings()
