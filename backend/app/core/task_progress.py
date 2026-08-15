"""任务级进度判定（后台完善 4/9）。任务列表进度口径唯一判定源，供 list_tasks 使用。

口径（用户拍板）：y = 任务词条总数，x = 已录词条数（跨全部发音人，任意状态，去重），
z = 已通过词条数（approved，去重）。完成状态 5 态：
已关闭 → 归档；已录 100% → 已完成；已发布且已过截止 → 已截止；已录 / 总数 ≥
TASK_NEAR_COMPLETE_RATIO → 接近完成；其余 → 进行中。
"""

from datetime import datetime, timezone

from ..core.config import settings


def completion_status(status: str, recorded: int, total: int, deadline_at=None) -> str:
    """返回 archived / completed / expired / near_complete / in_progress。

    已关闭任务优先判为归档；已录 ≥ 总数（total>0）为已完成（完成优先于到期）；
    已发布且设置了截止时间并已过 → 已截止（expired）；已录占比 ≥ 阈值（config 可调）为接近完成。
    deadline_at 可为 None（未设截止时间）或 aware datetime。
    """
    if status == "closed":
        return "archived"
    if total > 0 and recorded >= total:
        return "completed"
    if status == "published" and deadline_at is not None and deadline_at < datetime.now(timezone.utc):
        return "expired"
    if total > 0 and recorded / total >= settings.TASK_NEAR_COMPLETE_RATIO:
        return "near_complete"
    return "in_progress"
