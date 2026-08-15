"""任务级进度判定（后台完善 4）。任务列表进度口径唯一判定源，供 list_tasks 使用。

口径（用户拍板）：y = 任务词条总数，x = 已录词条数（跨全部发音人，任意状态，去重），
z = 已通过词条数（approved，去重）。完成状态 4 态：
已关闭 → 归档；已录 100% → 已完成；已录 / 总数 ≥ TASK_NEAR_COMPLETE_RATIO → 接近完成；其余 → 进行中。
"""

from ..core.config import settings


def completion_status(status: str, recorded: int, total: int) -> str:
    """返回 archived / completed / near_complete / in_progress。

    已关闭任务优先判为归档；已录 ≥ 总数（total>0）为已完成；已录占比 ≥ 阈值（config 可调）为接近完成。
    """
    if status == "closed":
        return "archived"
    if total > 0 and recorded >= total:
        return "completed"
    if total > 0 and recorded / total >= settings.TASK_NEAR_COMPLETE_RATIO:
        return "near_complete"
    return "in_progress"
