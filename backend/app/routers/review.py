"""录音审核（管理后台，阶段三）。

管理员按任务/状态分页查看录音，试听后通过/驳回，打通 recordings.status
的 pending → approved/rejected 流转。省管理员仅能看/审本省任务的录音。
"""
import csv
import io
import logging
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.deps import get_current_admin
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/review", tags=["review"])

VALID_STATUS = {"pending", "approved", "rejected"}
VALID_SORTS = {"pending_first", "created", "duration", "reviewed"}

# 发音人画像码 → manifest 中文显示（值域与 mp.py 的 GENDERS/AGE_BRACKETS 保持一致）
GENDER_LABELS = {"male": "男", "female": "女", "other": "其他"}
AGE_BRACKET_LABELS = {
    "under18": "<18",
    "age18_30": "18-30",
    "age31_45": "31-45",
    "age46_60": "46-60",
    "over60": ">60",
}


def _scope_query(db: Session, admin: AdminUser, q):
    """省管理员只能看到本省任务下的录音。"""
    if admin.role == "province_admin" and admin.province_code:
        q = q.join(TaskBatch, Recording.task_id == TaskBatch.id)
        q = q.filter(TaskBatch.province_code == admin.province_code)
    return q


def _enrich(rec: Recording, db: Session) -> ReviewRecordingOut:
    """把一条录音富化成带展示字段的 out（list 与 verdict 复用）。"""
    task = db.get(TaskBatch, rec.task_id)
    word = db.get(WordLibrary, rec.word_id)
    speaker = db.get(Speaker, rec.speaker_id)
    reviewer = db.get(AdminUser, rec.reviewed_by) if rec.reviewed_by else None
    return ReviewRecordingOut(
        id=rec.id,
        task_id=rec.task_id,
        task_name=task.name if task else f"任务#{rec.task_id}",
        province_code=task.province_code if task else None,
        word_id=rec.word_id,
        word_code=word.code if word else None,
        word_content=word.content if word else f"词条#{rec.word_id}",
        word_dialect_point=word.dialect_point if word else None,
        word_example_sentence=word.example_sentence if word else None,
        word_pronunciation_hint=word.pronunciation_hint if word else None,
        word_remark=word.remark if word else None,
        speaker_id=rec.speaker_id,
        speaker_nickname=speaker.nickname if speaker else None,
        speaker_device=speaker.device_id if speaker else None,
        speaker_gender=speaker.gender if speaker else None,
        speaker_age_bracket=speaker.age_bracket if speaker else None,
        audio_url=storage.play_url(rec.audio_url),  # COS→预签名；本地→相对路径
        audio_duration=rec.audio_duration,
        file_size=rec.file_size,
        mandarin_transcript=rec.mandarin_transcript,
        dialect_transcript=rec.dialect_transcript,
        status=rec.status,
        review_note=rec.review_note,
        reviewed_by=rec.reviewed_by,
        reviewed_by_name=reviewer.name if reviewer else None,
        created_at=rec.created_at,
        reviewed_at=rec.reviewed_at,
    )


@router.get("/recordings")
def list_review_recordings(
    task_id: int | None = None,
    status: str | None = None,
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
    rec.reviewed_by = admin.id
    rec.reviewed_at = datetime.now(timezone.utc)
    word = db.get(WordLibrary, rec.word_id)
    log_admin_action(
        db,
        admin,
        "审核通过" if body.approved else "审核驳回",
        "recording",
        rec.id,
        summary=f"录音 #{rec.id}「{word.content if word else rec.word_id}」{'通过' if body.approved else '驳回'}"
        + (f"（{body.note}）" if body.note else ""),
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


EXPORT_COLUMNS = [
    "recording_id",
    "task_id",
    "task_name",
    "province_code",
    "word_id",
    "word_code",
    "word_content",
    "word_dialect_point",
    "word_example_sentence",
    "word_pronunciation_hint",
    "word_remark",
    "mandarin_transcript",
    "dialect_transcript",
    "speaker_id",
    "speaker_nickname",
    "speaker_device",
    "speaker_gender",
    "speaker_age_bracket",
    "audio_file",
    "audio_present",
    "audio_duration_ms",
    "file_size",
    "recorded_at",
    "reviewed_at",
]


@router.get("/export")
def export_approved_recordings(
    task_id: int | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """批量导出已通过录音：ZIP = audios/（音频原文件）+ manifest.csv（utf-8-sig，Excel 可直接打开）。

    大文件友好：逐条落盘暂存 → 磁盘上构建 ZIP（deflate 分块读盘）→ StreamingResponse 分块流式返回。
    内存峰值 ≈ 单条录音大小（而非全部总和），避免大量录音导出时 OOM。
    """
    q = db.query(Recording)
    q = _scope_query(db, admin, q)  # 省管理员只导出本省任务
    if task_id is not None:
        q = q.filter(Recording.task_id == task_id)
    q = q.filter(Recording.status == "approved")
    recs = q.order_by(Recording.task_id, Recording.id).all()
    if not recs:
        raise HTTPException(status_code=400, detail="没有符合条件的已通过录音")

    rows = []
    staged = []  # (临时文件路径, zip 内路径)
    tmp = tempfile.TemporaryDirectory()
    try:
        for rec in recs:
            out = _enrich(rec, db)
            # 按省+任务嵌套归档：audios/{province_code}/task_{task_id}/{文件名}
            province = out.province_code or "unknown"
            zip_name = f"audios/{province}/task_{rec.task_id}/{Path(rec.audio_url).name}"
            content = storage.read_object(rec.audio_url)  # COS/本地统一读字节（单条进内存）
            present = content is not None
            if present:
                tmp_file = os.path.join(tmp.name, f"rec_{rec.id}.bin")
                with open(tmp_file, "wb") as f:
                    f.write(content)
                staged.append((tmp_file, zip_name))
            else:
                logger.warning(
                    "export: audio missing for recording %s (%s)", rec.id, rec.audio_url
                )
            rows.append(
                {
                    "recording_id": rec.id,
                    "task_id": rec.task_id,
                    "task_name": out.task_name,
                    "province_code": out.province_code,
                    "word_id": rec.word_id,
                    "word_code": out.word_code,
                    "word_content": out.word_content,
                    "word_dialect_point": out.word_dialect_point or "",
                    "word_example_sentence": out.word_example_sentence or "",
                    "word_pronunciation_hint": out.word_pronunciation_hint or "",
                    "word_remark": out.word_remark or "",
                    "mandarin_transcript": out.mandarin_transcript or "",
                    "dialect_transcript": out.dialect_transcript or "",
                    "speaker_id": rec.speaker_id,
                    "speaker_nickname": out.speaker_nickname,
                    "speaker_device": out.speaker_device,
                    "speaker_gender": GENDER_LABELS.get(out.speaker_gender, out.speaker_gender or ""),
                    "speaker_age_bracket": AGE_BRACKET_LABELS.get(
                        out.speaker_age_bracket, out.speaker_age_bracket or ""
                    ),
                    "audio_file": zip_name if present else "",
                    "audio_present": 1 if present else 0,
                    "audio_duration_ms": rec.audio_duration,
                    "file_size": len(content) if present else rec.file_size,
                    "recorded_at": rec.created_at.isoformat() if rec.created_at else "",
                    "reviewed_at": rec.reviewed_at.isoformat() if rec.reviewed_at else "",
                }
            )

        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

        # 磁盘构建 ZIP：zf.write 分块读暂存文件压缩，ZIP 不整包驻内存
        zip_path = os.path.join(tmp.name, "export.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for tmp_file, arcname in staged:
                zf.write(tmp_file, arcname)
            zf.writestr("manifest.csv", text.getvalue().encode("utf-8-sig"))

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"dialect_dataset_{ts}.zip"

        def gen():
            try:
                with open(zip_path, "rb") as f:
                    while True:
                        chunk = f.read(1 << 20)  # 1MB 分块
                        if not chunk:
                            break
                        yield chunk
            finally:
                tmp.cleanup()  # 正常流完或客户端断开（GeneratorExit）都清理临时目录

        return StreamingResponse(
            gen(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fname}"; filename*=UTF-8\'\'{quote(fname)}'},
        )
    except Exception:
        tmp.cleanup()
        raise
