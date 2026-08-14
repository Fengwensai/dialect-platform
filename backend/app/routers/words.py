from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..core.deps import get_current_admin
from ..db import get_db
from ..models.admin import AdminUser
from ..models.task import TaskBatch, TaskBatchItem
from ..models.task_claim import TaskClaim
from ..models.word import WordLibrary
from ..schemas.word import WordOut, WordUpdate
from ..services.region_matcher import match_region

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
    db.delete(word)
    db.commit()
    return {"ok": True}
