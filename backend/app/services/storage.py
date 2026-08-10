"""录音对象存储：腾讯云 COS（私有桶 + 预签名 URL），未配凭据回退本地磁盘。

统一收口录音文件（recordings/*）的 写/读/删/URL。头像仍在本地（MEDIA_ROOT/avatars），
/static 挂载保留。

COS 模式（COS_SECRET_ID/KEY/REGION/BUCKET 四项齐全）：
- put_object/delete_object/read_object 直接操作 COS 对象；
- play_url 返回预签名 GET URL（供前端 <audio> 审核试听）；
- media_url 返回预签名 URL（供微信 media_check_async 服务器下载）。

本地兜底（与现状字节级一致，本地开发/未配 COS 时行为不变）：
- 写读删走 MEDIA_ROOT 磁盘；play_url 原样返回 /media/... 相对路径；
- media_url 用 MEDIA_PUBLIC_BASE 拼接公网 URL，MEDIA_PUBLIC_BASE 为空返回 None。

线程安全：模块级懒加载单例 + threading.Lock；多 worker（多进程）各自持有实例，
CosS3Client 每次请求独立签名、无跨进程共享状态。
"""
import logging
import threading
from pathlib import Path

from ..core.config import settings

logger = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()
_client_override = None  # 测试注入点（fake client），见 scripts/verify_cos_mode.py


def enabled() -> bool:
    """四项凭据齐全才启用 COS，否则走本地磁盘兜底。"""
    return bool(
        settings.COS_SECRET_ID
        and settings.COS_SECRET_KEY
        and settings.COS_REGION
        and settings.COS_BUCKET
    )


def set_client_override(client) -> None:
    """测试专用：注入 fake client，绕过真实 SDK（无需真实凭据）。"""
    global _client_override
    _client_override = client


def clear_client_override() -> None:
    global _client_override
    _client_override = None


def _build_client():
    from qcloud_cos import CosConfig, CosS3Client  # 延迟 import：未启用时不依赖 SDK

    return CosS3Client(
        CosConfig(
            Region=settings.COS_REGION,
            SecretId=settings.COS_SECRET_ID,
            SecretKey=settings.COS_SECRET_KEY,
            Scheme="https",
        )
    )


def get_client():
    """当前存储客户端；未启用 COS 时返回 None（调用方走本地兜底）。"""
    global _client
    if _client_override is not None:
        return _client_override
    if not enabled():
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _build_client()
    return _client


def _key(logical_path: str) -> str:
    """/media/recordings/1/1_2_1.wav -> recordings/1/1_2_1.wav（COS 对象 key）。"""
    return logical_path.removeprefix("/media/")


def _disk_path(logical_path: str) -> Path:
    return Path(settings.MEDIA_ROOT) / logical_path.removeprefix("/media/")


_AUDIO_CONTENT_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


def _content_type(logical_path: str) -> str:
    return _AUDIO_CONTENT_TYPES.get(Path(logical_path).suffix.lower(), "application/octet-stream")


def put_object(logical_path: str, content: bytes) -> None:
    """写对象（COS put_object / 本地 write_bytes，父目录自动创建）。"""
    client = get_client()
    if client is None:
        p = _disk_path(logical_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return
    try:
        client.put_object(
            Bucket=settings.COS_BUCKET,
            Key=_key(logical_path),
            Body=content,
            ContentType=_content_type(logical_path),
        )
    except Exception as exc:  # noqa: BLE001 上传失败要向上抛（录音落库依赖它）
        logger.error("[storage] put_object 失败 key=%s: %s", _key(logical_path), exc)
        raise


def delete_object(logical_path: str) -> None:
    """删对象。COS DELETE 幂等（key 不存在返回 204）；本地不存在则跳过。删除失败不阻断。"""
    client = get_client()
    if client is None:
        p = _disk_path(logical_path)
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass
        return
    try:
        client.delete_object(Bucket=settings.COS_BUCKET, Key=_key(logical_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[storage] delete_object 失败 key=%s: %s", _key(logical_path), exc)


def read_object(logical_path: str) -> bytes | None:
    """读对象字节；不存在/失败返回 None（供导出 ZIP 缺文件兜底，不抛错）。"""
    client = get_client()
    if client is None:
        p = _disk_path(logical_path)
        if not p.is_file():
            return None
        return p.read_bytes()
    try:
        resp = client.get_object(Bucket=settings.COS_BUCKET, Key=_key(logical_path))
        body = resp["Body"].get_raw_stream()
        try:
            return body.read()
        finally:
            body.close()
    except Exception as exc:  # noqa: BLE001 含 CosServiceError(404)
        logger.warning("[storage] read_object 失败 key=%s: %s", _key(logical_path), exc)
        return None


def media_url(logical_path: str, expires: int = 3600) -> str | None:
    """供 content_security 的可下载公网 URL。COS→预签名；本地→MEDIA_PUBLIC_BASE 拼接。"""
    client = get_client()
    if client is None:
        if not settings.MEDIA_PUBLIC_BASE:
            return None
        return settings.MEDIA_PUBLIC_BASE.rstrip("/") + logical_path
    return client.get_presigned_url(
        Method="GET",
        Bucket=settings.COS_BUCKET,
        Key=_key(logical_path),
        Expired=expires,  # 默认 300s 太短，微信 media_check_async 处理窗口约 30 分钟
    )


def play_url(logical_path: str, expires: int = 3600) -> str:
    """供前端 <audio> 播放。COS→预签名 URL；本地→原样返回相对路径 /media/...。"""
    client = get_client()
    if client is None:
        return logical_path
    return client.get_presigned_url(
        Method="GET",
        Bucket=settings.COS_BUCKET,
        Key=_key(logical_path),
        Expired=expires,
    )
