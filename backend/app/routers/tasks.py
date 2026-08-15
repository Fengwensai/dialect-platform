from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.deps import get_current_admin
from ..core.task_progress import completion_status
from ..db import get_db
from ..models.admin import AdminUser
from ..models.recording import Recording
from ..models.speaker import Speaker
from ..models.task import TaskBatch, TaskBatchItem
from ..models.task_claim import TaskClaim
from ..models.team_code import TeamCode
from ..models.word import WordLibrary
from ..schemas.task import TaskBatchCreate, TaskBatchOut, TaskBatchUpdate, TaskClaimAdminOut
from ..schemas.word import WordOut
from ..services import rate_limit
from ..services.audit import log_admin_action

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _normalize(code: str) -> str:
    return (code or "").strip().upper()


def _resolve_team(db: Session, admin: AdminUser, code: str) -> TeamCode:
    """校验团队码存在且省管理员限本省，返回团队（地区由团队码带出）。"""
    tc = db.query(TeamCode).filter(TeamCode.code == _normalize(code)).first()
    if tc is None:
        raise HTTPException(status_code=422, detail="团队码不存在")
    if admin.role == "province_admin" and tc.province_code != admin.province_code:
        raise HTTPException(status_code=403, detail="只能关联本省的团队码")
    return tc


def _scope_query(db: Session, admin: AdminUser):
    q = db.query(TaskBatch)
    if admin.role == "province_admin" and admin.province_code:
        q = q.filter(TaskBatch.province_code == admin.province_code)
    return q


def _reject_occupied(
    db: Session, word_ids: list[int], exclude_task_id: int | None = None
):
    """占用制守卫：word_ids 中若有词条已被其它草稿/已发布任务占用则 400。

    exclude_task_id：编辑草稿任务时排除当前任务自身词条（自己的词条合法）。
    """
    if not word_ids:
        return
    occ_q = (
        db.query(TaskBatchItem.word_id)
        .join(TaskBatch, TaskBatch.id == TaskBatchItem.task_batch_id)
        .filter(TaskBatch.status.in_(["draft", "published"]))
        .filter(TaskBatchItem.word_id.in_(word_ids))
    )
    if exclude_task_id:
        occ_q = occ_q.filter(TaskBatchItem.task_batch_id != exclude_task_id)
    occupied_ids = {r[0] for r in occ_q.all()}
    if occupied_ids:
        names = {
            w.id: w.content
            for w in db.query(WordLibrary).filter(WordLibrary.id.in_(occupied_ids)).all()
        }
        label = "、".join(names.get(i, f"#{i}") for i in sorted(occupied_ids))
        raise HTTPException(status_code=400, detail=f"词条「{label}」已被其它任务占用，不能重复使用")


@router.post("", response_model=TaskBatchOut)
def create_task(
    body: TaskBatchCreate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    team_code = _normalize(body.team_code) if body.team_code else None
    province_code = body.province_code
    city_code = body.city_code or None
    district_code = body.district_code or None

    if team_code:
        # 关联团队：地区由团队码带出，传入的省/市必须与团队一致（否则 422）
        tc = _resolve_team(db, admin, team_code)
        if province_code != tc.province_code or city_code != tc.city_code:
            raise HTTPException(
                status_code=422,
                detail="任务地区与团队码地区不一致，选择团队后地区由团队码自动带出",
            )
        province_code, city_code, district_code = tc.province_code, tc.city_code, None
    elif admin.role == "province_admin" and province_code != admin.province_code:
        raise HTTPException(status_code=403, detail="只能给自己管辖省份创建任务")

    if body.is_demo and admin.role != "super_admin":
        raise HTTPException(status_code=403, detail="仅超管可创建演示任务")

    words = db.query(WordLibrary).filter(WordLibrary.id.in_(body.word_ids)).all()
    if admin.role == "province_admin":
        words = [w for w in words if w.province_code == admin.province_code]
    _reject_occupied(db, [w.id for w in words])

    batch = TaskBatch(
        name=body.name,
        description=body.description,
        province_code=province_code,
        city_code=city_code,
        district_code=district_code,
        team_code=team_code,
        required_audio_count=body.required_audio_count,
        claim_limit=body.claim_limit,
        status="draft",
        created_by=admin.id,
        is_demo=body.is_demo,
    )
    db.add(batch)
    db.flush()
    for w in words:
        db.add(TaskBatchItem(task_batch_id=batch.id, word_id=w.id))
    db.commit()
    db.refresh(batch)

    out = TaskBatchOut.model_validate(batch)
    out.word_count = len(words)
    return out


@router.get("")
def list_tasks(
    status: str | None = None,
    team_code: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    q = _scope_query(db, admin)
    if status:
        q = q.filter(TaskBatch.status == status)
    if team_code:
        q = q.filter(TaskBatch.team_code == _normalize(team_code))
    total = q.count()
    batches = (
        q.order_by(TaskBatch.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    if batches:
        batch_ids = [b.id for b in batches]
        counts = dict(
            db.query(TaskBatchItem.task_batch_id, func.count())
            .filter(TaskBatchItem.task_batch_id.in_(batch_ids))
            .group_by(TaskBatchItem.task_batch_id)
            .all()
        )
        # 任务级进度（后台完善 4）：跨全部发音人、按词条去重（重录覆盖旧行）
        rec_counts = dict(
            db.query(Recording.task_id, func.count(func.distinct(Recording.word_id)))
            .filter(Recording.task_id.in_(batch_ids))
            .group_by(Recording.task_id)
            .all()
        )
        appr_counts = dict(
            db.query(Recording.task_id, func.count(func.distinct(Recording.word_id)))
            .filter(Recording.task_id.in_(batch_ids), Recording.status == "approved")
            .group_by(Recording.task_id)
            .all()
        )
    else:
        counts = {}
        rec_counts = {}
        appr_counts = {}

    items = []
    for b in batches:
        out = TaskBatchOut.model_validate(b)
        out.word_count = counts.get(b.id, 0)
        out.recorded_count = rec_counts.get(b.id, 0)
        out.approved_count = appr_counts.get(b.id, 0)
        out.completion_status = completion_status(b.status, out.recorded_count, out.word_count)
        items.append(out)
    return {"total": total, "items": items}


@router.post("/{batch_id}/publish", response_model=TaskBatchOut)
def publish_task(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    batch = db.get(TaskBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if admin.role == "province_admin" and batch.province_code != admin.province_code:
        raise HTTPException(status_code=403, detail="无权操作其他省份任务")
    if batch.status != "draft":
        raise HTTPException(status_code=400, detail="仅草稿任务可发布")

    batch.status = "published"
    batch.published_at = datetime.now(timezone.utc)
    log_admin_action(
        db, admin, "发布任务", "task", batch.id,
        summary=f"发布任务 #{batch.id}「{batch.name}」",
        ip=rate_limit.client_ip(request),
    )
    db.commit()
    db.refresh(batch)

    word_count = (
        db.query(func.count())
        .select_from(TaskBatchItem)
        .filter(TaskBatchItem.task_batch_id == batch.id)
        .scalar()
        or 0
    )
    out = TaskBatchOut.model_validate(batch)
    out.word_count = word_count
    return out


def _get_task(db: Session, admin: AdminUser, batch_id: int) -> TaskBatch:
    """按 id 取任务并校验存在 + 省管理员属地。"""
    batch = db.get(TaskBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if admin.role == "province_admin" and batch.province_code != admin.province_code:
        raise HTTPException(status_code=403, detail="无权操作其他省份任务")
    return batch


def _word_count(db: Session, batch_id: int) -> int:
    return (
        db.query(func.count())
        .select_from(TaskBatchItem)
        .filter(TaskBatchItem.task_batch_id == batch_id)
        .scalar()
        or 0
    )


def _task_out(db: Session, batch: TaskBatch) -> TaskBatchOut:
    out = TaskBatchOut.model_validate(batch)
    out.word_count = _word_count(db, batch.id)
    return out


@router.get("/{batch_id}/words", response_model=list[WordOut])
def task_words(
    batch_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """任务包含的词条清单（按加入顺序）。"""
    _get_task(db, admin, batch_id)
    words = (
        db.query(WordLibrary)
        .join(TaskBatchItem, TaskBatchItem.word_id == WordLibrary.id)
        .filter(TaskBatchItem.task_batch_id == batch_id)
        .order_by(TaskBatchItem.id)
        .all()
    )
    return [WordOut.model_validate(w) for w in words]


@router.patch("/{batch_id}", response_model=TaskBatchOut)
def update_task(
    batch_id: int,
    body: TaskBatchUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """编辑草稿任务：改名称/说明/必录数，词条整体替换。仅草稿可编辑。"""
    batch = _get_task(db, admin, batch_id)
    if batch.status != "draft":
        raise HTTPException(status_code=400, detail="仅草稿任务可编辑")

    data = body.model_dump(exclude_unset=True)
    if data.get("name"):
        batch.name = data["name"].strip()
    if "description" in data:
        batch.description = data["description"]
    if data.get("required_audio_count"):
        batch.required_audio_count = data["required_audio_count"]
    if "claim_limit" in data:
        batch.claim_limit = data["claim_limit"]
    if "team_code" in data:
        team_code = _normalize(data["team_code"]) if data["team_code"] else None
        if team_code:
            # 改绑团队：地区由团队码带出并覆盖，district 清空（团队仅到市一级）
            tc = _resolve_team(db, admin, team_code)
            batch.province_code = tc.province_code
            batch.city_code = tc.city_code
            batch.district_code = None
            batch.team_code = tc.code
        else:
            # 解除关联：保留当前地区，仅去掉团队码归属
            batch.team_code = None
    if data.get("word_ids") is not None:
        words = db.query(WordLibrary).filter(WordLibrary.id.in_(data["word_ids"])).all()
        if admin.role == "province_admin":
            words = [w for w in words if w.province_code == admin.province_code]
        # 占用制：编辑时排除当前任务自身词条，自己的词条合法
        _reject_occupied(db, [w.id for w in words], exclude_task_id=batch.id)
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == batch.id).delete()
        for w in words:
            db.add(TaskBatchItem(task_batch_id=batch.id, word_id=w.id))

    db.commit()
    db.refresh(batch)
    return _task_out(db, batch)


@router.post("/{batch_id}/close", response_model=TaskBatchOut)
def close_task(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """关闭已发布任务：小程序端不再展示，已采集录音保留。"""
    batch = _get_task(db, admin, batch_id)
    if batch.status != "published":
        raise HTTPException(status_code=400, detail="仅已发布任务可关闭")
    batch.status = "closed"
    log_admin_action(
        db, admin, "关闭任务", "task", batch.id,
        summary=f"关闭任务 #{batch.id}「{batch.name}」",
        ip=rate_limit.client_ip(request),
    )
    db.commit()
    db.refresh(batch)
    return _task_out(db, batch)


@router.post("/{batch_id}/reopen", response_model=TaskBatchOut)
def reopen_task(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """重新打开已关闭任务：小程序端重新展示，可继续采录，已采集录音保留。"""
    batch = _get_task(db, admin, batch_id)
    if batch.status != "closed":
        raise HTTPException(status_code=400, detail="仅已关闭任务可重新打开")
    batch.status = "published"
    batch.published_at = datetime.now(timezone.utc)
    log_admin_action(
        db, admin, "重新打开任务", "task", batch.id,
        summary=f"重新打开任务 #{batch.id}「{batch.name}」",
        ip=rate_limit.client_ip(request),
    )
    db.commit()
    db.refresh(batch)
    return _task_out(db, batch)


@router.delete("/{batch_id}")
def delete_task(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """删除任务（连带词条关联、领取记录）。任意状态（草稿/已发布/已关闭）可删除；已有录音则拒绝。"""
    batch = _get_task(db, admin, batch_id)
    has_recording = (
        db.query(func.count())
        .select_from(Recording)
        .filter(Recording.task_id == batch_id)
        .scalar()
        or 0
    )
    if has_recording:
        raise HTTPException(status_code=400, detail="该任务已有录音，不能删除")
    db.query(TaskClaim).filter(TaskClaim.task_id == batch.id).delete()
    db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == batch.id).delete()
    log_admin_action(
        db, admin, "删除任务", "task", batch.id,
        summary=f"删除任务 #{batch.id}「{batch.name}」",
        ip=rate_limit.client_ip(request),
    )
    db.delete(batch)
    db.commit()
    return {"detail": "已删除"}


@router.get("/{batch_id}/claims", response_model=list[TaskClaimAdminOut])
def task_claims_list(
    batch_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """任务领取情况（领取制）：每条领取对应的词条/发音人/是否已录，供后台解绑。"""
    _get_task(db, admin, batch_id)
    claims = (
        db.query(TaskClaim)
        .filter(TaskClaim.task_id == batch_id)
        .order_by(TaskClaim.word_id)
        .all()
    )
    if not claims:
        return []
    word_ids = [c.word_id for c in claims]
    speaker_ids = [c.speaker_id for c in claims]
    word_map = {
        w.id: w
        for w in db.query(WordLibrary).filter(WordLibrary.id.in_(word_ids)).all()
    }
    speaker_map = {
        s.id: s for s in db.query(Speaker).filter(Speaker.id.in_(speaker_ids)).all()
    }
    recorded_words = {
        r[0]
        for r in db.query(Recording.word_id)
        .filter(Recording.task_id == batch_id, Recording.word_id.in_(word_ids))
        .all()
    }
    return [
        TaskClaimAdminOut(
            claim_id=c.id,
            word_id=c.word_id,
            content=word_map[c.word_id].content if c.word_id in word_map else "",
            speaker_id=c.speaker_id,
            nickname=speaker_map[c.speaker_id].nickname
            if c.speaker_id in speaker_map
            else "",
            recorded=c.word_id in recorded_words,
            claimed_at=c.claimed_at,
        )
        for c in claims
    ]


@router.delete("/{batch_id}/claims/{claim_id}")
def admin_unbind_claim(
    batch_id: int,
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """管理端解绑领取：仅未录制的词条可解绑（已录 400），解绑后词条回池。"""
    _get_task(db, admin, batch_id)
    claim = db.get(TaskClaim, claim_id)
    if claim is None or claim.task_id != batch_id:
        raise HTTPException(status_code=404, detail="领取记录不存在")
    rec = (
        db.query(Recording)
        .filter(
            Recording.task_id == batch_id,
            Recording.word_id == claim.word_id,
            Recording.speaker_id == claim.speaker_id,
        )
        .first()
    )
    if rec is not None:
        raise HTTPException(status_code=400, detail="该词条已录制，不能解绑")
    log_admin_action(
        db, admin, "解绑领取", "claim", claim_id,
        summary=f"任务 #{batch_id} 词条 #{claim.word_id} 解绑领取（发音人 #{claim.speaker_id}）",
        ip=rate_limit.client_ip(request),
    )
    db.delete(claim)
    db.commit()
    return {"detail": "已解绑"}
