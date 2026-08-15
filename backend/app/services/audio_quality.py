"""录音质量自动预检（纯标准库，无第三方音频依赖）。

解析小程序端上传的 WAV（16kHz 单声道 16bit PCM，wav.js 补 44 字节 RIFF 头），
计算 duration_ms / rms_db / silence_ratio 三指标，按阈值打 too_short / silent / too_quiet
标记并归类 status（ok / suspect / unparsed）。

- 非 WAV（mp3/m4a/aac）或解析失败 → analyze_audio_quality 返回 None，上层记 unparsed。
- 阈值集中在 Settings（QUALITY_*，.env 可覆盖），便于上线后按实际语料调参。
- 检测只做标记，不拦截上传、不自动驳回；审核仍人工，见 docs 待办。
"""
import io
import math
import sys
import wave
from array import array

# 静音判定阈值（归一化幅值）：|sample| < 0.02 ≈ -34 dBFS 视为静音帧
SILENCE_AMP_NORM = 0.02
# 各位深下的满幅归一化分母（8bit unsigned=128，16bit=32768，32bit signed=2^31）
_MAX_SAMPLE = {1: 128.0, 2: 32768.0, 4: 2147483648.0}
# 每块读帧数（约 1s @16k），控制大文件内存
_CHUNK_FRAMES = 16384


def analyze_audio_quality(content: bytes) -> dict | None:
    """解析 WAV 字节，返回 {duration_ms, rms_db, silence_ratio}；非 WAV/解析失败返回 None。"""
    if not content or len(content) < 12:
        return None
    # 魔数校验：RIFF....WAVE（不信任扩展名，防止伪装音频）
    if content[:4] != b"RIFF" or content[8:12] != b"WAVE":
        return None
    try:
        with wave.open(io.BytesIO(content), "rb") as w:
            framerate = w.getframerate()
            sampwidth = w.getsampwidth()
            nframes = w.getnframes()
            if (
                framerate <= 0
                or sampwidth not in _MAX_SAMPLE
                or nframes <= 0
            ):
                return None
            need_swap = sys.byteorder != "little"  # WAV 恒为小端，大端机器需换字节序
            max_sample = _MAX_SAMPLE[sampwidth]
            sum_sq = 0.0
            silent = 0
            total = 0
            while True:
                raw = w.readframes(_CHUNK_FRAMES)
                if not raw:
                    break
                if sampwidth == 1:
                    # 8bit unsigned PCM：有符号化 = 减去 128
                    for b in raw:
                        n = abs((b - 128) / max_sample)
                        total += 1
                        if n < SILENCE_AMP_NORM:
                            silent += 1
                        sum_sq += n * n
                else:
                    a = array("h" if sampwidth == 2 else "i")
                    a.frombytes(raw)
                    if need_swap:
                        a.byteswap()
                    for s in a:
                        n = abs(s / max_sample)
                        total += 1
                        if n < SILENCE_AMP_NORM:
                            silent += 1
                        sum_sq += n * n
    except (wave.Error, ValueError, EOFError):
        return None
    if total == 0:
        return None
    rms = math.sqrt(sum_sq / total)
    rms_db = 20.0 * math.log10(rms + 1e-12)
    return {
        "duration_ms": int(round(nframes / framerate * 1000)),
        "rms_db": round(rms_db, 1),
        "silence_ratio": round(silent / total, 4),
    }


def classify(metrics: dict) -> tuple[str, list[str]]:
    """按阈值把指标归类为 (status, flags)。status ∈ ok/suspect；flags 为旗标列表。"""
    from app.core.config import settings

    flags: list[str] = []
    if metrics["duration_ms"] < settings.QUALITY_MIN_DURATION_MS:
        flags.append("too_short")
    if metrics["silence_ratio"] >= settings.QUALITY_SILENCE_RATIO:
        flags.append("silent")
    if metrics["rms_db"] < settings.QUALITY_MIN_RMS_DB:
        flags.append("too_quiet")
    return ("suspect" if flags else "ok", flags)
