"""微信内容安全：文本 msgSecCheck + 音频 media_check_async（上线准备）。

fail-open 原则：微信接口不可达 / 未配 Secret / 非明确违规 一律放行，绝不阻断核心业务
（登录、上传、改昵称）。任何日志不打印微信凭据与待检正文。

- get_access_token：cgi-bin/token，模块级缓存到 expires_in-300s，失败返回 None。
- check_text：POST /wxa/msg_sec_check {content}；errcode==87014 视为违规，其它放行。
- check_media_async：POST /wxa/media_check_async 发起异步检测，返回 trace_id（结果推送需
  公网消息接收 URL，域名部署后才可用，本期仅发起 + 存 trace_id）。
"""
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from ..core.config import settings
from ..db import SessionLocal
from ..services import storage

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
_TEXT_URL = "https://api.weixin.qq.com/wxa/msg_sec_check"
_MEDIA_URL = "https://api.weixin.qq.com/wxa/media_check_async"

# access_token 缓存：token + 过期时刻（epoch 秒）。reserve 提前 300s 换新。
_reserve_secs = 300
_access = {"token": None, "expires_at": 0.0}
_lock = threading.Lock()


@dataclass
class TextCheckResult:
    passed: bool = True  # 是否放行
    blocked: bool = False  # 是否命中明确违规（87014）
    reason: str = ""
    errcode: int | None = None


def get_access_token() -> str | None:
    """获取微信 access_token（带缓存）。未配 Secret / 请求失败 → None（fail-open）。"""
    if not settings.WECHAT_SECRET:
        return None
    now = datetime.now(timezone.utc).timestamp()
    with _lock:
        if _access["token"] and _access["expires_at"] > now + _reserve_secs:
            return _access["token"]
        try:
            resp = requests.get(
                _TOKEN_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": settings.WECHAT_APPID or "",
                    "secret": settings.WECHAT_SECRET,
                },
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token")
            expires_in = data.get("expires_in") or 7200
            if not token:
                logger.error("[content_security] access_token 获取失败: %s", data.get("errcode"))
                return None
            _access["token"] = token
            _access["expires_at"] = now + int(expires_in)
            return token
        except requests.RequestException as exc:
            logger.error("[content_security] access_token 请求异常: %s", exc)
            return None


def _wechat_post(url: str, token: str, body: dict) -> dict:
    """POST 微信接口并返回 JSON。网络异常抛给调用方（上层按 fail-open 处理）。"""
    resp = requests.post(url, params={"access_token": token}, json=body, timeout=8)
    resp.raise_for_status()
    return resp.json()


def check_text(content: str, scene: int = 1) -> TextCheckResult:
    """文本内容安全检测。errcode==87014 违规；微信不可达/无 Secret/其它错误一律放行。"""
    result = TextCheckResult()
    token = get_access_token()
    if not token:
        return result
    try:
        data = _wechat_post(_TEXT_URL, token, {"content": content, "scene": scene})
    except (requests.RequestException, ValueError) as exc:
        logger.error("[content_security] msg_sec_check 请求异常: %s", exc)
        return result
    errcode = data.get("errcode")
    result.errcode = errcode
    if errcode == 87014:
        result.blocked = True
        result.passed = False
        result.reason = data.get("errmsg", "") or "内容违规"
    elif errcode not in (0, None):
        # 非违规的业务错误（如 47001 参数错）不影响放行，仅记录
        logger.warning("[content_security] msg_sec_check 非违规错误码: %s", errcode)
    return result


def check_media_async(openid: str, media_url: str) -> str | None:
    """发起音频异步内容检测（media_check_async）。返回 trace_id；失败 → None。

    media_url 需微信检测服务器可下载（公网 URL）。结果异步推送到消息接收服务器，
    域名部署后凭 trace_id 对账回写；本期仅发起。
    """
    token = get_access_token()
    if not token:
        return None
    try:
        data = _wechat_post(
            _MEDIA_URL,
            token,
            {
                "version": 2,
                "openid": openid,
                "scene": 2,
                "media_type": 1,  # 1 = 音频
                "media_url": media_url,
            },
        )
    except (requests.RequestException, ValueError) as exc:
        logger.error("[content_security] media_check_async 请求异常: %s", exc)
        return None
    trace_id = data.get("trace_id")
    if trace_id:
        return trace_id
    logger.error("[content_security] media_check_async 未返回 trace_id: %s", data.get("errcode"))
    return None


def fire_media_check(recording_id: int) -> None:
    """后台任务：为录音发起音频内容检测，回填 trace_id + content_check_status。

    自开 Session（规避请求生命周期里 db 关闭）；未配 COS 且未配 MEDIA_PUBLIC_BASE 时
    media_url() 返回 None 直接跳过。全程 try/except 吞错，发起失败不影响上传响应。
    """
    try:
        from ..models.recording import Recording  # 延迟导入避免循环依赖

        db = SessionLocal()
        try:
            rec = db.get(Recording, recording_id)
            if rec is None or rec.audio_url.startswith("/media/") is False:
                return
            media_url = storage.media_url(rec.audio_url)  # COS→预签名；本地→MEDIA_PUBLIC_BASE 拼接
            if not media_url:
                return
            openid = ""
            # 尽量带 openid（media_check_async 要求用户近两小时访问过小程序，无则留空由微信判断）
            if rec.speaker_id:
                from ..models.speaker import Speaker

                sp = db.get(Speaker, rec.speaker_id)
                if sp and sp.openid:
                    openid = sp.openid
            trace_id = check_media_async(openid, media_url)
            rec.media_check_trace_id = trace_id
            rec.content_check_status = "media_pending" if trace_id else "media_failed"
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 后台任务不许外抛
        logger.error("[content_security] fire_media_check(%s) 失败: %s", recording_id, exc)
