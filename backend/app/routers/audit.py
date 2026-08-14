"""操作审计日志查询（后台完善项 6）。

只读端点，超管可见：按管理员/操作/关键词/时间区间分页倒序查看
admin_operation_logs（谁、何时、做了什么）。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..core.deps import require_super_admin
from ..db import get_db
from ..models.admin import AdminUser
from ..models.audit_log import AdminOperationLog
from ..schemas.audit import AuditLogOut

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
