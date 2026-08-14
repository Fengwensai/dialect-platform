from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .routers import (
    agreements,
    audit,
    auth,
    dashboard,
    excel,
    mp,
    regions,
    review,
    speakers,
    tasks,
    team_codes,
    users,
    wechat,
    words,
)

app = FastAPI(title="方言采集平台 - 管理后台 API")

# CORS 白名单可配置：开发默认 "*" 放开，上线在 .env 的 CORS_ORIGINS 收紧为具体域名。
# 注意：通配 "*" + allow_credentials=True 是浏览器规范下的非法组合（预检会失败），
# 本项目鉴权走 Authorization header 而非 cookie，因此通配时关闭 credentials。
_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False if "*" in _origins else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(audit.router)
app.include_router(excel.router)
app.include_router(words.router)
app.include_router(regions.router)
app.include_router(tasks.router)
app.include_router(users.router)
app.include_router(agreements.router)
app.include_router(mp.router)
app.include_router(review.router)
app.include_router(speakers.router)
app.include_router(dashboard.router)
app.include_router(team_codes.router)
app.include_router(wechat.router)

# 媒体目录（录音文件）静态服务，浏览器/小程序可直接试听
MEDIA_DIR = Path(settings.MEDIA_ROOT)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


@app.get("/api/health")
def health():
    return {"status": "ok"}
