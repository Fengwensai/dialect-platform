"""操作审计日志查询（后台完善项 6/9）。

只读端点，超管可见：按管理员/操作/关键词/时间区间分页倒序查看
admin_operation_logs（谁、何时、做了什么）；另有审核员工作量/质量报表
（纯派生自 recordings，按 reviewed_by 聚合条数/通过率/驳回原因分布）。
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..core.deps import require_super_admin
from ..core.reject_reasons import LABELS as REJECT_REASON_LABELS
from ..db import get_db
from ..models.admin import AdminUser
from ..models.audit_log import AdminOperationLog
from ..models.recording import Recording
from ..schemas.audit import AuditLogOut, AuditWorkloadOut, WorkloadReason, WorkloadRow

router = APIRouter(prefix="/api/audit-logs", tags=["audit-logs"])


def _as_utc(dt: datetime) -> datetime:
    """naive 时间按 UTC 处理（录音 created_at 存 UTC），避免与时区字段比较错位。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("")
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    action: str | None = None,
    admin_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_super_admin),
):
    """分页查看审计日志，按时间倒序。keyword 匹配管理员昵称/摘要。"""
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="开始时间不能晚于结束时间")
    q = db.query(AdminOperationLog)
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(
            or_(
                AdminOperationLog.admin_name.like(like),
                AdminOperationLog.summary.like(like),
            )
        )
    if action:
        q = q.filter(AdminOperationLog.action == action)
    if admin_id is not None:
        q = q.filter(AdminOperationLog.admin_id == admin_id)
    if start:
        q = q.filter(AdminOperationLog.created_at >= _as_utc(start))
    if end:
        q = q.filter(AdminOperationLog.created_at <= _as_utc(end))

    total = q.count()
    items = (
        q.order_by(AdminOperationLog.created_at.desc(), AdminOperationLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "items": [AuditLogOut.model_validate(i) for i in items],
    }


@router.get("/workload", response_model=AuditWorkloadOut)
def audit_workload(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_super_admin),
):
    """审核员工作量/质量报表（后台完善 9）：近 days 天按审核员聚合条数/通过率/驳回原因分布。

    数据源为 recordings（reviewed_by / reviewed_at / status / reject_reasons），纯派生无迁移。
    注意：「重置为待审」会清空审核字段、「删除录音」会物理删行，因此这两类动作不计入本报表
    （属审计日志范畴）。滚动窗口（days=1 即近 24 小时）；驳回原因逗号拆串计数，未标注计入 unknown。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(Recording.reviewed_by, Recording.status, Recording.reject_reasons)
        .filter(Recording.reviewed_at >= cutoff, Recording.reviewed_by.isnot(None))
        .all()
    )

    agg: dict[int, dict] = {}
    for admin_id, status, reasons in rows:
        a = agg.setdefault(
            admin_id,
            {"total": 0, "approved": 0, "rejected": 0, "reason_counts": {}},
        )
        a["total"] += 1
        if status == "approved":
            a["approved"] += 1
        elif status == "rejected":
            a["rejected"] += 1
            if reasons:
                for k in reasons.split(","):
                    a["reason_counts"][k] = a["reason_counts"].get(k, 0) + 1
            else:
                a["reason_counts"]["unknown"] = a["reason_counts"].get("unknown", 0) + 1

    items = []
    for admin_id, a in agg.items():
        au = db.get(AdminUser, admin_id)
        name = (au.name or au.username) if au is not None else f"#{admin_id}"
        reasons = [
            WorkloadReason(key=k, label=REJECT_REASON_LABELS.get(k, k), count=c)
            for k, c in sorted(a["reason_counts"].items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        items.append(
            WorkloadRow(
                admin_id=admin_id,
                admin_name=name,
                total=a["total"],
                approved=a["approved"],
                rejected=a["rejected"],
                approval_rate=a["approved"] / a["total"] if a["total"] else 0.0,
                reasons=reasons,
            )
        )
    items.sort(key=lambda r: -r.total)
    return AuditWorkloadOut(items=items, total=len(items), days=days)
