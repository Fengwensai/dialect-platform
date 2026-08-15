"""数据完整性巡检（后台完善 7）：无 FK 兜底，扫描并修复孤儿引用。

所有表间是逻辑引用（无 FOREIGN KEY），正常删除路径已逐项在应用层清理引用，
但历史数据或绕过应用层的写入仍可能留下「子行指向不存在的父行」的孤儿。
本模块提供两类操作：
- scan_orphans(db)：扫描 9 类核心 NOT NULL 业务引用，返回分类汇总 + 明细。
- repair_orphans(db, admin, ...)：删除孤儿行（孤儿录音连带清存储文件）+ 审计。
"""

from sqlalchemy.orm import Session

from ..models.agreement import SpeakerAgreement
from ..models.recording import Recording
from ..models.speaker import Speaker
from ..models.task import TaskBatch, TaskBatchItem
from ..models.task_claim import TaskClaim
from ..models.word import WordLibrary
from ..schemas.data_health import (
    DataHealthReport,
    OrphanCategory,
    OrphanItem,
    RepairResult,
)
from ..services import storage
from ..services.audit import log_admin_action


class _Check:
    """一类孤儿引用检查：子表某列（NOT NULL）指向父表 id。"""

    def __init__(
        self,
        key: str,
        name: str,
        child,
        col: str,
        parent,
        child_label: str,
        parent_label: str,
        recording: bool = False,
    ):
        self.key = key
        self.name = name
        self.child = child
        self.col = col
        self.parent = parent
        self.child_label = child_label
        self.parent_label = parent_label
        self.recording = recording  # 子行是录音 → 修复时连带清理音频文件


ORPHAN_CHECKS = [
    _Check("recording_word", "录音→词条", Recording, "word_id", WordLibrary, "录音", "词条", recording=True),
    _Check("recording_task", "录音→任务", Recording, "task_id", TaskBatch, "录音", "任务", recording=True),
    _Check("recording_speaker", "录音→发音人", Recording, "speaker_id", Speaker, "录音", "发音人", recording=True),
    _Check("item_batch", "任务条目→任务", TaskBatchItem, "task_batch_id", TaskBatch, "任务条目", "任务"),
    _Check("item_word", "任务条目→词条", TaskBatchItem, "word_id", WordLibrary, "任务条目", "词条"),
    _Check("claim_task", "领取记录→任务", TaskClaim, "task_id", TaskBatch, "领取记录", "任务"),
    _Check("claim_word", "领取记录→词条", TaskClaim, "word_id", WordLibrary, "领取记录", "词条"),
    _Check("claim_speaker", "领取记录→发音人", TaskClaim, "speaker_id", Speaker, "领取记录", "发音人"),
    _Check("agreement_speaker", "协议记录→发音人", SpeakerAgreement, "speaker_id", Speaker, "协议记录", "发音人"),
]

# 每类最多返回的明细条数（count 仍全量，明细截断防止大表返回过载）
MAX_ITEMS = 200


def _orphan_query(db: Session, check: _Check):
    """子表 col 不在父表 id 集合中的行（悬空引用）。父表 id 为主键永不为 NULL，无 NOT IN 空集陷阱。"""
    parent_ids = db.query(check.parent.id).subquery()
    return db.query(check.child).filter(getattr(check.child, check.col).notin_(parent_ids))


def scan_orphans(db: Session) -> DataHealthReport:
    """扫描全部孤儿引用，返回分类汇总 + 每类前 MAX_ITEMS 条明细。"""
    categories: list[OrphanCategory] = []
    total = 0
    for check in ORPHAN_CHECKS:
        base = _orphan_query(db, check)
        count = base.count()
        total += count
        rows = base.order_by(check.child.id).limit(MAX_ITEMS).all()
        items = [
            OrphanItem(
                id=r.id,
                ref=str(getattr(r, check.col)),
                detail=f"{check.child_label} #{r.id} → {check.parent_label} #{getattr(r, check.col)}",
            )
            for r in rows
        ]
        categories.append(
            OrphanCategory(key=check.key, name=check.name, count=count, items=items)
        )
    return DataHealthReport(total=total, categories=categories)


def repair_orphans(
    db: Session,
    admin,
    category: str | None = None,
    ids: list[int] | None = None,
    ip: str = "",
) -> RepairResult:
    """一键修复：删除孤儿行（孤儿录音先清理音频文件）+ 审计留痕。

    category 为 None 修全部 9 类；ids 限定该类中指定子行（非孤儿行天然不会命中）。
    单事务：全部删除后一次 commit，中途异常整体 rollback。
    """
    checks = [c for c in ORPHAN_CHECKS if category is None or c.key == category]
    deleted: dict[str, int] = {}
    total = 0
    for check in checks:
        q = _orphan_query(db, check)
        if ids:
            q = q.filter(check.child.id.in_(ids))
        rows = q.all()
        for r in rows:
            if check.recording:
                storage.delete_object(r.audio_url)  # COS/本地统一，失败不阻断
            db.delete(r)
        deleted[check.key] = len(rows)
        total += len(rows)

    if total == 0:
        return RepairResult(deleted=deleted, total=0)

    summary = "、".join(f"{k}={v}" for k, v in deleted.items() if v)
    log_admin_action(
        db,
        admin,
        "数据健康修复",
        "system",
        summary=f"修复孤儿引用 {total} 条（{summary}）",
        detail=deleted,
        ip=ip,
    )
    db.commit()
    return RepairResult(deleted=deleted, total=total)
