"""发音人质量预警（后台完善 3）：通过率 + 最少已审核条数。

无审核历史表（录音被重录/重置后原判决覆盖），无法可靠重建「严格连续 N 条驳回」，
故用当前快照通过率近似「持续低通过率」，与看板统计口径一致。
"""

from ..core.config import settings


def warning_state(approved: int, rejected: int) -> tuple[bool, float, int]:
    """返回 (是否预警, 通过率 0~1, 已审核条数)。

    已审核（通过+驳回）≥ SPEAKER_WARN_MIN_REVIEWED 且通过率 < SPEAKER_WARN_APPROVAL_RATE
    → 标黄预警。无已审核记录时通过率按 1.0 计（不预警）。
    """
    reviewed = approved + rejected
    rate = approved / reviewed if reviewed else 1.0
    warned = (
        reviewed >= settings.SPEAKER_WARN_MIN_REVIEWED
        and rate < settings.SPEAKER_WARN_APPROVAL_RATE
    )
    return warned, rate, reviewed
