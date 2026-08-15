"""数据完整性巡检端点（后台完善 7）：扫描孤儿引用 + 一键修复（仅超管）。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..core.deps import require_super_admin
from ..db import get_db
from ..models.admin import AdminUser
from ..schemas.data_health import (
    DataHealthReport,
    RepairRequest,
    RepairResult,
)
from ..services import data_health, rate_limit

router = APIRouter(prefix="/api/data-health", tags=["data-health"])


@router.get("", response_model=DataHealthReport)
def check_data_health(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_super_admin),
):
    """扫描全部孤儿引用（录音/任务条目/领取/协议记录指向不存在的父行）。"""
    return data_health.scan_orphans(db)


@router.post("/repair", response_model=RepairResult)
def repair_data_health(
    request: Request,
    body: RepairRequest | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_super_admin),
):
    """一键修复：删除孤儿行（孤儿录音连带清理音频文件）+ 审计留痕。

    body 可空（修全部）；可传 {category, ids} 定向修复。
    """
    if body is None:
        body = RepairRequest()
    valid = {c.key for c in data_health.ORPHAN_CHECKS}
    if body.category is not None and body.category not in valid:
        raise HTTPException(status_code=400, detail=f"未知孤儿分类: {body.category}")
    return data_health.repair_orphans(
        db, admin, body.category, body.ids, rate_limit.client_ip(request)
    )
