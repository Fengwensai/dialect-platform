"""微信「消息接收地址」：内容安全 media_check_async 结果回调。

mp 后台「开发 → 开发设置 → 消息推送」把 URL 配到本端点（明文模式）：
- GET  /api/wechat/callback：配置 URL 时的验签，通过回显 echostr。
- POST /api/wechat/callback：接收 wxa_media_check 事件推送，回写录音状态。
本端点公开（无鉴权），依赖验签保护 + 仅按 trace_id 回写；任何失败都回 "success"，
避免微信重试风暴，同时保证核心业务不被推送异常影响。
"""
import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..core.config import settings
from ..db import get_db
from ..services.wechat_push import apply_media_check, parse_body, verify_signature

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wechat", tags=["wechat"])


@router.get("/callback")
def wechat_callback_verify(
    signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
    echostr: str = Query(""),
):
    """URL 验证：微信配置消息接收地址时 GET 验签，通过则原样回显 echostr。"""
    if verify_signature(settings.WECHAT_MSG_TOKEN, timestamp, nonce, signature):
        return PlainTextResponse(echostr)
    logger.warning("[wechat] URL 验签失败: ts=%s nonce=%s sig=%s", timestamp, nonce, signature)
    return PlainTextResponse("signature error")


@router.post("/callback")
async def wechat_callback(
    request: Request,
    signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
    db: Session = Depends(get_db),
):
    """接收微信事件推送。wxa_media_check 按 trace_id 回写录音状态；其它事件忽略。"""
    if not verify_signature(settings.WECHAT_MSG_TOKEN, timestamp, nonce, signature):
        logger.warning("[wechat] 推送验签失败，忽略")
        return PlainTextResponse("success")
    raw = await request.body()
    payload = parse_body(raw)
    if payload and str(payload.get("Event") or "") == "wxa_media_check":
        try:
            apply_media_check(db, payload)
        except Exception as exc:  # noqa: BLE001 推送失败不影响业务，且避免微信重试风暴
            logger.error("[wechat] 内容安全结果回写失败: %s", exc)
    else:
        logger.info("[wechat] 非内容安全事件，忽略: %s", str(payload)[:120])
    return PlainTextResponse("success")
