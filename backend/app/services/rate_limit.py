"""轻量进程内限流：登录防爆破 + 上传频率限流。

固定窗口计数，线程安全。默认 uvicorn 单进程部署下计数准确；多 worker 时各进程独立
计数，仍能显著抬高攻击门槛（如需跨进程严格计数可换 DB/Redis，当前项目未引入）。
"""
import threading
import time

_lock = threading.Lock()
_counters: dict[str, tuple[float, int]] = {}  # key -> (窗口起点时间戳, 计数)
_PURGE_BOUND = 1000  # 键数超过该阈值时清理过期项，防止长期运行内存无界增长
_MAX_TTL = 3600  # 清理时按此上限判定过期（所有窗口均远小于 1 小时）


def client_ip(request) -> str:
    """取客户端 IP：优先 X-Forwarded-For 首段（Nginx 反代场景），回退直连地址。"""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def reset(key: str) -> None:
    """手动清零（如登录成功后清除该账号/IP 的失败计数）。"""
    with _lock:
        _counters.pop(key, None)


def blocked(key: str, limit: int, window_seconds: int) -> bool:
    """窗口内计数已达上限则拒绝（不改变计数）。"""
    now = time.time()
    with _lock:
        start, count = _counters.get(key, (now, 0))
        if now - start >= window_seconds:
            return False
        return count >= limit


def record_failure(key: str, limit: int, window_seconds: int) -> bool:
    """登录失败等事件计数 +1，返回是否已触发锁定（本次失败后达到上限）。"""
    now = time.time()
    with _lock:
        _maybe_purge(now)
        start, count = _counters.get(key, (now, 0))
        if now - start >= window_seconds:
            start, count = now, 0
        _counters[key] = (start, count + 1)
        return count + 1 >= limit


def consume(key: str, limit: int, window_seconds: int) -> bool:
    """放行类限流（上传等）：窗口内已消费 < limit 则计数 +1 放行，否则拒绝。"""
    now = time.time()
    with _lock:
        _maybe_purge(now)
        start, count = _counters.get(key, (now, 0))
        if now - start >= window_seconds:
            start, count = now, 0
        if count >= limit:
            return False
        _counters[key] = (start, count + 1)
        return True


def _maybe_purge(now: float) -> None:
    if len(_counters) < _PURGE_BOUND:
        return
    expired = [k for k, (start, _) in _counters.items() if now - start > _MAX_TTL]
    for k in expired:
        _counters.pop(k, None)
