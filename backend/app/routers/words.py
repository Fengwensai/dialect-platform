from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..core.deps import get_current_admin
from ..db import get_db
from ..models.admin import AdminUser
from ..models.recording import Recording
from ..models.task import TaskBatch, TaskBatchItem
from ..models.task_claim import TaskClaim
from ..models.word import WordLibrary
from ..schemas.word import WordMergeRequest, WordOut, WordUpdate
from ..services import rate_limit, storage
from ..services.audit import log_admin_action
from ..services.region_matcher import match_region
from .speakers import _pick_better_recording

router = APIRouter(prefix="/api/words", tags=["words"])


def _scope_query(db: Session, admin: AdminUser):
    q = db.query(WordLibrary)
    if admin.role == "province_admin" and admin.province_code:
        q = q.filter(WordLibrary.province_code == admin.province_code)
    return q


@router.get("")
def list_words(
    province_code: str | None = None,
    city_code: str | None = None,
    district_code: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    exclude_task_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    q = _scope_query(db, admin)
    # 省管理员限定本省：显式传入的省参数钳制为本省，避免越权查看/返回空
    if admin.role == "province_admin" and admin.province_code:
        province_code = admin.province_code
    if province_code:
        q = q.filter(WordLibrary.province_code == province_code)
    if city_code:
        q = q.filter(WordLibrary.city_code == city_code)
    if district_code:
        q = q.filter(WordLibrary.district_code == district_code)
    if status:
        if status not in ("active", "disabled"):
            raise HTTPException(status_code=422, detail="status 仅支持 active/disabled")
        q = q.filter(WordLibrary.status == status)
    if keyword:
        kw = f"%{keyword.strip()}%"
        q = q.filter(
            or_(
                WordLibrary.content.like(kw),
                WordLibrary.dialect_point.like(kw),
                WordLibrary.code.like(kw),
            )
        )
    total = q.count()
    items = (
        q.order_by(WordLibrary.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    # 占用制：草稿/已发布任务中的词条被占用（占用仍在列表，仅前端置灰+标签）。
    # exclude_task_id 用于编辑草稿任务时排除自身词条，避免把自己判为已占用。
    occ_q = (
        db.query(TaskBatchItem.word_id)
        .join(TaskBatch, TaskBatch.id == TaskBatchItem.task_batch_id)
        .filter(TaskBatch.status.in_(["draft", "published"]))
    )
    if exclude_task_id:
        occ_q = occ_q.filter(TaskBatchItem.task_batch_id != exclude_task_id)
    occupied_ids = {r[0] for r in occ_q.all()}

    out = []
    for w in items:
        o = WordOut.model_validate(w)
        o.occupied = w.id in occupied_ids
        out.append(o)
    return {
        "total": total,
        "items": out,
    }


@router.get("/check-duplicate")
def check_duplicate_word(
    content: str = "",
    exclude_word_id: int | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """词条查重（仅提示不拦截）：content 全局精确匹配，排除自身，命中返回第一条。

    前端编辑保存前调用，命中则弹「已存在相同内容词条」确认；确认后仍可保存。
    """
    content = (content or "").strip()
    if not content:
        return {"duplicate": False, "word": None}
    q = db.query(WordLibrary).filter(WordLibrary.content == content)
    if exclude_word_id:
        q = q.filter(WordLibrary.id != exclude_word_id)
    dup = q.order_by(WordLibrary.id).first()
    if dup is None:
        return {"duplicate": False, "word": None}
    return {
        "duplicate": True,
        "word": {
            "id": dup.id,
            "code": dup.code,
            "content": dup.content,
            "dialect_point": dup.dialect_point,
        },
    }


@router.post("/merge")
def merge_words(
    body: WordMergeRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """词条合并：把 remove_word 的引用并入 keep_word，然后删除 remove_word。

    引用迁移：Recording.word_id / TaskClaim.word_id / TaskBatchItem.word_id。
    冲突处理：录音按状态保留策略去重（approved>rejected>pending，同级留新，淘汰者连带删存储对象）；
    领取/任务包引用若目标已存在则删除 remove 的（保持 UNIQUE(task,word)/(task_batch,word)）。
    """
    keep = db.get(WordLibrary, body.keep_word_id)
    remove = db.get(WordLibrary, body.remove_word_id)
    if keep is None or remove is None:
        raise HTTPException(status_code=404, detail="词条不存在")
    if keep.id == remove.id:
        raise HTTPException(status_code=400, detail="不能合并同一个词条")
    for w in (keep, remove):
        if admin.role == "province_admin" and w.province_code != admin.province_code:
            raise HTTPException(status_code=403, detail="无权操作其他省份词条")

    moved_rec = removed_rec = moved_claim = removed_claim = moved_item = removed_item = 0

    # —— Recording：迁移 word_id，冲突按状态保留策略去重 ——
    target_recs = {
        (r.task_id, r.speaker_id): r
        for r in db.query(Recording).filter(Recording.word_id == keep.id).all()
    }
    for r in db.query(Recording).filter(Recording.word_id == remove.id).all():
        key = (r.task_id, r.speaker_id)
        existing = target_recs.get(key)
        if existing is None:
            r.word_id = keep.id
            target_recs[key] = r
            moved_rec += 1
        else:
            better = _pick_better_recording(existing, r)
            loser = existing if better is r else r
            storage.delete_object(loser.audio_url)  # 淘汰者连带清理存储
            db.delete(loser)
            better.word_id = keep.id  # 胜者（无论原属哪方）统一归到 keep，避免孤儿引用
            target_recs[key] = better
            removed_rec += 1

    # —— TaskClaim：迁移，同 (task, keep) 已被领取则删 remove 的 ——
    keep_claim_tasks = {c.task_id for c in db.query(TaskClaim).filter(TaskClaim.word_id == keep.id).all()}
    for cl in db.query(TaskClaim).filter(TaskClaim.word_id == remove.id).all():
        if cl.task_id in keep_claim_tasks:
            db.delete(cl)
            removed_claim += 1
        else:
            cl.word_id = keep.id
            keep_claim_tasks.add(cl.task_id)
            moved_claim += 1

    # —— TaskBatchItem：迁移，同 (task_batch, keep) 已存在则删 remove 的 ——
    keep_item_tasks = {it.task_batch_id for it in db.query(TaskBatchItem).filter(TaskBatchItem.word_id == keep.id).all()}
    for it in db.query(TaskBatchItem).filter(TaskBatchItem.word_id == remove.id).all():
        if it.task_batch_id in keep_item_tasks:
            db.delete(it)
            removed_item += 1
        else:
            it.word_id = keep.id
            keep_item_tasks.add(it.task_batch_id)
            moved_item += 1

    log_admin_action(
        db,
        admin,
        "合并词条",
        "word",
        keep.id,
        summary=f"合并词条 #{remove.id}「{remove.content}」→ #{keep.id}「{keep.content}」",
        detail={
            "moved_recordings": moved_rec,
            "removed_recordings": removed_rec,
            "moved_claims": moved_claim,
            "removed_claims": removed_claim,
            "moved_items": moved_item,
            "removed_items": removed_item,
        },
        ip=rate_limit.client_ip(request),
    )
    db.delete(remove)
    db.commit()
    return {
        "detail": "已合并",
        "moved_recordings": moved_rec,
        "removed_recordings": removed_rec,
        "moved_claims": moved_claim,
        "removed_claims": removed_claim,
        "moved_items": moved_item,
        "removed_items": removed_item,
    }


@router.patch("/{word_id}", response_model=WordOut)
def update_word(
    word_id: int,
    body: WordUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    word = db.get(WordLibrary, word_id)
    if word is None:
        raise HTTPException(status_code=404, detail="词条不存在")
    if admin.role == "province_admin" and word.province_code != admin.province_code:
        raise HTTPException(status_code=403, detail="无权操作其他省份词条")

    data = body.model_dump(exclude_unset=True)
    if "status" in data and data.get("status") not in ("active", "disabled"):
        raise HTTPException(status_code=422, detail="status 仅支持 active/disabled")
    # 显式传了区划则用显式值；只改方言点时自动重新匹配
    explicit_region = any(k in data for k in ("province_code", "city_code", "district_code"))
    if "dialect_point" in data and not explicit_region:
        region = match_region(db, data.get("dialect_point") or word.dialect_point)
        data["province_code"] = region["province_code"] or word.province_code
        data["city_code"] = region["city_code"] or word.city_code
        data["district_code"] = region["district_code"] or word.district_code
    for k, v in data.items():
        setattr(word, k, v)

    db.commit()
    db.refresh(word)
    return word


@router.delete("/{word_id}")
def delete_word(
    word_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    word = db.get(WordLibrary, word_id)
    if word is None:
        raise HTTPException(status_code=404, detail="词条不存在")
    if admin.role == "province_admin" and word.province_code != admin.province_code:
        raise HTTPException(status_code=403, detail="无权操作其他省份词条")
    # 清理任务包中的引用，避免孤儿数据；领取记录一并清，防止孤儿 claim 永久占池
    db.query(TaskClaim).filter(TaskClaim.word_id == word_id).delete()
    db.query(TaskBatchItem).filter(TaskBatchItem.word_id == word_id).delete()
    log_admin_action(
        db,
        admin,
        "删除词条",
        "word",
        word.id,
        summary=f"删除词条 #{word.id}「{word.content}」",
        ip=rate_limit.client_ip(request),
    )
    db.delete(word)
    db.commit()
    return {"ok": True}
