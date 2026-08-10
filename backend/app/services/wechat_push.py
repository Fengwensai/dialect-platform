"""微信消息推送接收（内容安全 media_check_async 结果回调）。

小程序「音频异步内容检测」的结果在 30 分钟内以 event 推送（Event=wxa_media_check）
发到后台配置的「消息接收地址」（开发→开发设置→消息推送，URL 验签用 GET echostr）。
本模块：
- verify_signature：URL 验证与推送验签（sha1(token, timestamp, nonce)）。
- parse_body：推送体解析为 dict，兼容 JSON 与 XML（官方新旧字段并存）。
- media_check_verdict：从推送字段判定 通过/违规/失败（isrisky / errcode / result.suggest / detail）。
- apply_media_check：按 trace_id 匹配录音并回写 content_check_status（幂等，可重试）。
"""
import hashlib
import json
import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# 媒体文件下载失败等「非内容问题」错误码（uint 形式 4294966288 = -1008）
MEDIA_FAIL_CODES = {-1008, 4294966288, 43104}
# 明确违规的错误码（msgSecCheck 同款 87014）
MEDIA_RISK_CODES = {87014}


def verify_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
    """微信验签：sha1(排序拼接 token/timestamp/nonce)。token 未配置时跳过（本地联调）。"""
    if not token:
        return True
    if not signature:
        return False
    s = "".join(sorted([token, str(timestamp), str(nonce)]))
    return hashlib.sha1(s.encode("utf-8")).hexdigest() == signature


def parse_body(raw: bytes) -> dict | None:
    """推送体 → dict。优先 JSON（官方示例），失败回退 XML（消息推送默认格式）。"""
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        pass
    try:
        root = ET.fromstring(raw)
        return {child.tag: (child.text or "") for child in root}
    except Exception as exc:
        logger.error("[wechat_push] 推送体解析失败: %s", exc)
        return None


def media_check_verdict(payload: dict) -> tuple[str, str]:
    """判定推送结果。返回 (状态, 原因)，状态 ∈ passed / blocked / failed / unknown。

    新旧版本字段并存：isrisky(0/1)、errcode、status_code、result.suggest、detail[].suggest。
    """
    status_code = payload.get("status_code")
    errcode = payload.get("errcode")
    if status_code in MEDIA_FAIL_CODES or errcode in MEDIA_FAIL_CODES:
        return "failed", f"媒体链接不可用（errcode={errcode or status_code}）"
    # 其它非零错误码：非内容风险，视为失败，避免误判违规
    if errcode not in (None, "", "0", 0) and errcode not in MEDIA_RISK_CODES:
        return "failed", f"检测任务异常（errcode={errcode}）"
    if status_code not in (None, "", "0", 0) and status_code not in MEDIA_FAIL_CODES:
        return "failed", f"检测任务异常（status_code={status_code}）"

    isrisky = payload.get("isrisky")
    if isrisky in (1, "1", True):
        return "blocked", payload.get("detail") or "检测到违规内容"
    if isrisky in (0, "0", False):
        return "passed", ""

    result = payload.get("result")
    if isinstance(result, dict):
        suggest = result.get("suggest")
        if suggest == "risky":
            return "blocked", payload.get("detail") or "检测到违规内容"
        if suggest == "pass":
            return "passed", ""

    detail = payload.get("detail")
    if isinstance(detail, list):
        sugg = [d.get("suggest") for d in detail if isinstance(d, dict)]
        if "risky" in sugg:
            return "blocked", "检测到违规内容"
        if sugg and all(s == "pass" for s in sugg):
            return "passed", ""
    return "unknown", "推送缺少判定字段"


def apply_media_check(db, payload: dict) -> str | None:
    """按 trace_id 匹配录音并回写 content_check_status。幂等；返回状态或 None。"""
    trace_id = str(payload.get("trace_id") or "").strip()
    if not trace_id:
        logger.warning("[wechat_push] 推送缺少 trace_id，忽略")
        return None
    from ..models.recording import Recording  # 延迟导入避免循环依赖

    rec = db.query(Recording).filter(Recording.media_check_trace_id == trace_id).first()
    if rec is None:
        logger.warning("[wechat_push] trace_id 未匹配到录音: %s", trace_id)
        return None
    status, reason = media_check_verdict(payload)
    if status == "blocked":
        rec.content_check_status = "media_blocked"
    elif status == "passed":
        rec.content_check_status = "media_passed"
    elif status == "failed":
        rec.content_check_status = "media_failed"
    else:
        logger.warning("[wechat_push] 判定字段缺失，不覆盖 recording %s", rec.id)
        return None
    db.commit()
    logger.info("[wechat_push] recording %s -> %s", rec.id, rec.content_check_status)
    return rec.content_check_status
