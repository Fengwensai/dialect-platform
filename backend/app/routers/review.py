"""录音审核（管理后台，阶段三）。

管理员按任务/状态分页查看录音，试听后通过/驳回，打通 recordings.status
的 pending → approved/rejected 流转。省管理员仅能看/审本省任务的录音。
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.deps import get_current_admin
from ..core.reject_reasons import LABELS as REJECT_REASON_LABELS
from ..core.reject_reasons import VALID_REJECT_REASONS
from ..db import get_db
from ..models.admin import AdminUser
from ..models.recording import Recording
from ..models.speaker import Speaker
from ..models.task import TaskBatch
from ..models.word import WordLibrary
from ..schemas.review import (
    BatchVerdictRequest,
    BatchVerdictResult,
    ReviewRecordingOut,
    TranscriptUpdate,
    VerdictRequest,
)
from ..services import rate_limit, storage
from ..services.audit import log_admin_action
from ..services.export import enrich_recording as _enrich, recordings_zip_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/review", tags=["review"])

VALID_STATUS = {"pending", "approved", "rejected"}
VALID_SORTS = {"pending_first", "created", "duration", "reviewed"}
VALID_QUALITY = {"ok", "suspect", "unparsed"}

def _scope_query(db: Session, admin: AdminUser, q):
    """省管理员只能看到本省任务下的录音。"""
    if admin.role == "province_admin" and admin.province_code:
        q = q.join(TaskBatch, Recording.task_id == TaskBatch.id)
        q = q.filter(TaskBatch.province_code == admin.province_code)
    return q


def _store_reasons(approved: bool, reasons: list[str] | None) -> str | None:
    """把驳回原因 key 列表整理成逗号串落库。

    - 通过（approved=True）或未选原因 → None（不存原因）。
    - 非法 key → 422（风格同 VALID_STATUS 校验）。
    - 合法则去重保序，逗号连接（如 "noise,misread"）。
    """
    if approved or not reasons:
        return None
    bad = [r for r in reasons if r not in VALID_REJECT_REASONS]
    if bad:
        raise HTTPException(status_code=422, detail=f"无效驳回原因: {bad}")
    return ",".join(dict.fromkeys(reasons))


def _reject_reason_summary(reasons: str | None) -> str:
    """把逗号串原因转审计日志用的中文串（如「背景噪音,念错」），空返回空串。"""
    if not reasons:
        return ""
    labels = [REJECT_REASON_LABELS.get(k, k) for k in reasons.split(",")]
    return f"（{'、'.join(labels)}）"


@router.get("/recordings")
def list_review_recordings(
    task_id: int | None = None,
    status: str | None = None,
    quality: str | None = None,
    keyword: str | None = None,
    province_code: str | None = None,
    sort_by: str = "pending_first",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """分页列出录音：任务/状态/关键词/地区筛选 + 排序（默认待审优先）。

    keyword 模糊匹配发音人（昵称/设备ID/openid）与词条（内容/编号）。省管理员自动钳制为本省任务。
    """
    if status is not None and status not in VALID_STATUS:
        raise HTTPException(status_code=422, detail="status 仅支持 pending/approved/rejected")
    if quality is not None and quality not in VALID_QUALITY:
        raise HTTPException(
            status_code=422, detail="quality 仅支持 ok/suspect/unparsed"
        )
    if sort_by not in VALID_SORTS:
        raise HTTPException(
            status_code=422, detail="sort_by 仅支持 pending_first/created/duration/reviewed"
        )

    q = db.query(Recording).join(TaskBatch, Recording.task_id == TaskBatch.id)
    if admin.role == "province_admin" and admin.province_code:
        q = q.filter(TaskBatch.province_code == admin.province_code)
    if task_id is not None:
        q = q.filter(Recording.task_id == task_id)
    if status is not None:
        q = q.filter(Recording.status == status)
    if quality is not None:
        q = q.filter(Recording.quality_status == quality)
    if province_code:
        q = q.filter(TaskBatch.province_code == province_code)
    if keyword:
        like = f"%{keyword.strip()}%"
        q = (
            q.join(Speaker, Recording.speaker_id == Speaker.id)
            .join(WordLibrary, Recording.word_id == WordLibrary.id)
            .filter(
                or_(
                    Speaker.nickname.like(like),
                    Speaker.device_id.like(like),
                    Speaker.openid.like(like),
                    WordLibrary.content.like(like),
                    WordLibrary.code.like(like),
                )
            )
        )

    total = q.count()
    order_clauses = {
        "pending_first": [
            case((Recording.status == "pending", 0), else_=1),
            Recording.created_at.desc(),
        ],
        "created": [Recording.created_at.desc(), Recording.id.desc()],
        "duration": [Recording.audio_duration.desc(), Recording.id.desc()],
        "reviewed": [
            case((Recording.reviewed_at.is_(None), 1), else_=0),
            Recording.reviewed_at.desc(),
            Recording.id.desc(),
        ],
    }
    recs = (
        q.order_by(*order_clauses[sort_by])
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_enrich(rec, db) for rec in recs]
    return {"total": total, "items": items}


@router.post("/recordings/{recording_id}/verdict", response_model=ReviewRecordingOut)
def review_verdict(
    recording_id: int,
    body: VerdictRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """通过/驳回一条录音；允许重复审核（改判覆盖）。"""
    rec = db.get(Recording, recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="录音不存在")

    task = db.get(TaskBatch, rec.task_id)
    if admin.role == "province_admin" and (
        task is None or task.province_code != admin.province_code
    ):
        raise HTTPException(status_code=403, detail="只能审核本省任务的录音")

    rec.status = "approved" if body.approved else "rejected"
    rec.review_note = body.note
    rec.reject_reasons = _store_reasons(body.approved, body.reasons)
    rec.reviewed_by = admin.id
    rec.reviewed_at = datetime.now(timezone.utc)
    word = db.get(WordLibrary, rec.word_id)
    reason_summary = _reject_reason_summary(rec.reject_reasons)
    note_suffix = f"（{body.note}）" if body.note else reason_summary
    log_admin_action(
        db,
        admin,
        "审核通过" if body.approved else "审核驳回",
        "recording",
        rec.id,
        summary=f"录音 #{rec.id}「{word.content if word else rec.word_id}」{'通过' if body.approved else '驳回'}"
        + note_suffix,
        ip=rate_limit.client_ip(request),
    )
    db.commit()
    db.refresh(rec)
    return _enrich(rec, db)


@router.post("/batch-verdict", response_model=BatchVerdictResult)
def batch_review_verdict(
    body: BatchVerdictRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """批量通过/驳回多条录音（只处理 pending，已审过的不再改动，避免覆盖人工判决）。

    省管理员自动跳过非本省任务的录音。返回实际改判数 processed 与跳过数 skipped。
    """
    ids = list(dict.fromkeys(body.recording_ids))  # 去重保序
    if not ids:
        raise HTTPException(status_code=400, detail="未选择任何录音")

    recs = db.query(Recording).filter(Recording.id.in_(ids)).all()
    rec_map = {r.id: r for r in recs}
    missing = [i for i in ids if i not in rec_map]
    if missing:
        raise HTTPException(status_code=404, detail=f"录音不存在: {missing}")

    task_map = {
        t.id: t
        for t in db.query(TaskBatch)
        .filter(TaskBatch.id.in_([r.task_id for r in recs]))
        .all()
    }
    now = datetime.now(timezone.utc)
    processed = 0
    for rid in ids:
        rec = rec_map[rid]
        task = task_map.get(rec.task_id)
        if admin.role == "province_admin" and (
            task is None or task.province_code != admin.province_code
        ):
            continue  # 越省：跳过
        if rec.status != "pending":
            continue  # 已审过：跳过，不改判
        rec.status = "approved" if body.approved else "rejected"
        rec.review_note = body.note
        rec.reject_reasons = _store_reasons(body.approved, body.reasons)
        rec.reviewed_by = admin.id
        rec.reviewed_at = now
        processed += 1

    if processed == 0:
        raise HTTPException(
            status_code=400, detail="所选录音均无需审核（已审过或不在本省范围）"
        )
    log_admin_action(
        db,
        admin,
        "批量审核通过" if body.approved else "批量审核驳回",
        "recording",
        summary=f"批量{'通过' if body.approved else '驳回'}录音 {processed} 条（跳过 {len(ids) - processed} 条）",
        detail={"processed": processed, "skipped": len(ids) - processed},
        ip=rate_limit.client_ip(request),
    )
    db.commit()
    return BatchVerdictResult(processed=processed, skipped=len(ids) - processed)


@router.post("/recordings/{recording_id}/reset", response_model=ReviewRecordingOut)
def reset_recording_to_pending(
    recording_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """驳回重置为待审：仅 rejected 可重置，撤销判决（清备注/审核人/审核时间）。

    转写（普通话/方言）与内容安全标记保留——转写是内容资产，重置只是让它重新排队。
    """
    rec = db.get(Recording, recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="录音不存在")

    task = db.get(TaskBatch, rec.task_id)
    if admin.role == "province_admin" and (
        task is None or task.province_code != admin.province_code
    ):
        raise HTTPException(status_code=403, detail="只能操作本省任务的录音")

    if rec.status != "rejected":
        raise HTTPException(status_code=400, detail="仅已驳回的录音可重置为待审")
    rec.status = "pending"
    rec.review_note = None
    rec.reject_reasons = None
    rec.reviewed_by = None
    rec.reviewed_at = None
    log_admin_action(
        db, admin, "重置为待审", "recording", rec.id,
        summary=f"重置录音 #{rec.id} 为待审",
        ip=rate_limit.client_ip(request),
    )
    db.commit()
    db.refresh(rec)
    return _enrich(rec, db)


@router.delete("/recordings/{recording_id}")
def delete_rejected_recording(
    recording_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """单条删除录音（仅 rejected）：清理存储对象 + 删除 DB 行。

    删除后该 (任务, 词条, 发音人) 不再有录音，发音人可重新录制（领取记录保留）。
    """
    rec = db.get(Recording, recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="录音不存在")

    task = db.get(TaskBatch, rec.task_id)
    if admin.role == "province_admin" and (
        task is None or task.province_code != admin.province_code
    ):
        raise HTTPException(status_code=403, detail="只能操作本省任务的录音")

    if rec.status != "rejected":
        raise HTTPException(status_code=400, detail="仅已驳回的录音可删除")
    storage.delete_object(rec.audio_url)  # COS/本地统一，失败不阻断
    log_admin_action(
        db, admin, "删除录音", "recording", rec.id,
        summary=f"删除录音 #{rec.id}",
        ip=rate_limit.client_ip(request),
    )
    db.delete(rec)
    db.commit()
    return {"detail": "已删除"}


@router.patch("/recordings/{recording_id}/transcript", response_model=ReviewRecordingOut)
def update_recording_transcript(
    recording_id: int,
    body: TranscriptUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """填写/更新录音转写（普通话/方言）。缺省不改；null/空串清空。"""
    rec = db.get(Recording, recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="录音不存在")

    task = db.get(TaskBatch, rec.task_id)
    if admin.role == "province_admin" and (
        task is None or task.province_code != admin.province_code
    ):
        raise HTTPException(status_code=403, detail="只能操作本省任务的录音")

    data = body.model_dump(exclude_unset=True)
    if "mandarin_transcript" in data:
        rec.mandarin_transcript = data["mandarin_transcript"] or None
    if "dialect_transcript" in data:
        rec.dialect_transcript = data["dialect_transcript"] or None
    db.commit()
    db.refresh(rec)
    return _enrich(rec, db)


@router.get("/export")
def export_approved_recordings(
    task_id: int | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """批量导出已通过录音：ZIP = audios/（音频原文件）+ manifest.csv（utf-8-sig，Excel 可直接打开）。

    ZIP 打包复用 services.export（磁盘暂存 → 磁盘构建 → 1MB 分块流式，内存峰值 ≈ 单条录音大小）。
    省管理员只导出本省任务。
    """
    q = db.query(Recording)
    q = _scope_query(db, admin, q)  # 省管理员只导出本省任务
    if task_id is not None:
        q = q.filter(Recording.task_id == task_id)
    q = q.filter(Recording.status == "approved")
    recs = q.order_by(Recording.task_id, Recording.id).all()
    if not recs:
        raise HTTPException(status_code=400, detail="没有符合条件的已通过录音")

    def arcname(rec, out):
        # 按省+任务嵌套归档：audios/{province_code}/task_{task_id}/{文件名}
        province = out.province_code or "unknown"
        return f"audios/{province}/task_{rec.task_id}/{Path(rec.audio_url).name}"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return recordings_zip_response(db, recs, arcname, f"dialect_dataset_{ts}.zip")
