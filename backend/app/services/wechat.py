"""微信 jscode2session：小程序登录 code → openid。

配置了 WECHAT_SECRET 时走真实微信接口；未配置时走开发兜底，
把 code 直接映射为 `dev_<code>` 的测试 openid（便于本地/无网联调）。
"""
import logging

import requests
from fastapi import HTTPException

from ..core.config import settings

logger = logging.getLogger(__name__)

_JSC2S_URL = "https://api.weixin.qq.com/sns/jscode2session"


def code_to_openid(code: str) -> str:
    if not code:
        raise HTTPException(status_code=400, detail="code 不能为空")

    # 开发兜底：未配置 Secret 时用确定性 openid，方便本地联调
    if not settings.WECHAT_SECRET:
        logger.warning("[wechat] WECHAT_SECRET 未配置，登录走开发兜底（openid=dev_%s）", code)
        return "dev_" + code

    try:
        resp = requests.get(
            _JSC2S_URL,
            params={
                "appid": settings.WECHAT_APPID or "",
                "secret": settings.WECHAT_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("[wechat] jscode2session 请求失败: %s", exc)
        raise HTTPException(status_code=502, detail="微信登录服务暂不可用") from exc

    if "openid" in data:
        return data["openid"]
    errmsg = data.get("errmsg") or ""
    if "code" in errmsg or data.get("errcode") in (40029, 40163, 40003):
        raise HTTPException(status_code=400, detail="code 无效或已过期")
    logger.error("[wechat] jscode2session 异常: %s", data)
    raise HTTPException(status_code=502, detail="微信登录服务异常")
