from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.deps import get_current_admin
from ..core.task_progress import completion_status
from ..db import get_db
from ..models.admin import AdminUser
from ..models.recording import Recording
from ..models.region import Region
from ..models.speaker import Speaker
from ..models.task import TaskBatch, TaskBatchItem
from ..models.task_claim import TaskClaim
from ..models.team_code import TeamCode
from ..models.word import WordLibrary
from ..schemas.task import TaskBatchCreate, TaskBatchOut, TaskBatchUpdate, TaskClaimAdminOut
from ..schemas.word import WordOut
from ..services import rate_limit
from ..services.audit import log_admin_action
from ..services.export import csv_response

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
        deadline_at=body.deadline_at,
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
        q.order_by(TaskBatch.id.asc())
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
        out.completion_status = completion_status(
            b.status, out.recorded_count, out.word_count, deadline_at=b.deadline_at
        )
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


@router.get("/{batch_id}", response_model=TaskBatchOut)
def task_detail(
    batch_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """任务详情（供任务详情页展示）：基本信息 + 任务级进度。"""
    batch = _get_task(db, admin, batch_id)
    out = _task_out(db, batch)
    out.recorded_count = (
        db.query(func.count(func.distinct(Recording.word_id)))
        .filter(Recording.task_id == batch.id)
        .scalar()
        or 0
    )
    out.approved_count = (
        db.query(func.count(func.distinct(Recording.word_id)))
        .filter(Recording.task_id == batch.id, Recording.status == "approved")
        .scalar()
        or 0
    )
    out.completion_status = completion_status(
        batch.status, out.recorded_count, out.word_count, deadline_at=batch.deadline_at
    )
    return out


def _task_contributor_rows(db: Session, batch_id: int) -> list[dict]:
    """任务下发音人贡献行（全量、发音人ID升序）：计数 + 时长聚合 + 团队/属地名。

    「有效时长」= 审核通过（approved）录音时长和；「无效时长」= 驳回（rejected）时长和。
    """
    agg_rows = (
        db.query(
            Recording.speaker_id,
            Recording.status,
            func.count(Recording.id),
            func.sum(Recording.audio_duration),
        )
        .filter(Recording.task_id == batch_id)
        .group_by(Recording.speaker_id, Recording.status)
        .all()
    )
    dur_map: dict[tuple[int, str], tuple[int, int]] = {
        (sid, st): (cnt, dur or 0) for sid, st, cnt, dur in agg_rows
    }
    speaker_ids = {sid for sid, _ in dur_map.keys()}
    if not speaker_ids:
        return []
    speakers = {
        s.id: s for s in db.query(Speaker).filter(Speaker.id.in_(speaker_ids)).all()
    }
    team_codes = {s.team_code for s in speakers.values() if s.team_code}
    teams = {
        t.code: t for t in db.query(TeamCode).filter(TeamCode.code.in_(team_codes)).all()
    }
    region_codes = {
        c
        for s in speakers.values()
        for c in (s.province_code, s.city_code, s.district_code)
        if c
    }
    region_names = {
        r.code: r.name
        for r in db.query(Region).filter(Region.code.in_(region_codes)).all()
    }
    last_active = dict(
        db.query(Recording.speaker_id, func.max(Recording.created_at))
        .filter(Recording.task_id == batch_id, Recording.speaker_id.in_(speaker_ids))
        .group_by(Recording.speaker_id)
        .all()
    )

    def _pick(sid, st):
        return dur_map.get((sid, st), (0, 0))

    rows = []
    for sid in speaker_ids:
        sp = speakers[sid]
        pending_c, pending_d = _pick(sid, "pending")
        approved_c, approved_d = _pick(sid, "approved")
        rejected_c, rejected_d = _pick(sid, "rejected")
        reviewed = approved_c + rejected_c
        rows.append({
            "speaker_id": sid,
            "nickname": sp.nickname or "",
            "device_id": sp.device_id or "",
            "team_code": sp.team_code or "",
            "team_name": teams[sp.team_code].name
            if sp.team_code and sp.team_code in teams else "",
            "province_name": region_names.get(sp.province_code, sp.province_code or ""),
            "city_name": region_names.get(sp.city_code, sp.city_code or ""),
            "district_name": region_names.get(sp.district_code, sp.district_code or ""),
            "recording_total": pending_c + approved_c + rejected_c,
            "pending": pending_c,
            "approved": approved_c,
            "rejected": rejected_c,
            "total_duration_ms": pending_d + approved_d + rejected_d,
            "valid_duration_ms": approved_d,
            "invalid_duration_ms": rejected_d,
            "approval_rate": round(approved_c / reviewed, 4) if reviewed else 0.0,
            "last_active": last_active.get(sid),
        })
    rows.sort(key=lambda x: x["speaker_id"])  # 发音人 ID 正序
    return rows


@router.get("/{batch_id}/contributors")
def task_contributors(
    batch_id: int,
    keyword: str | None = None,
    team_code: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """任务下发音人贡献分页列表（发音人ID升序）。

    summary 反映整个任务（不受筛选/分页影响），供详情页头部汇总。keyword 匹配昵称/设备ID。
    """
    _get_task(db, admin, batch_id)
    rows = _task_contributor_rows(db, batch_id)
    summary = {
        "speaker_count": len(rows),
        "recording_total": sum(r["recording_total"] for r in rows),
        "approved_total": sum(r["approved"] for r in rows),
        "valid_duration_ms": sum(r["valid_duration_ms"] for r in rows),
    }
    k = (keyword or "").strip().lower()
    tc = _normalize(team_code) if team_code else None
    if k or tc:
        rows = [
            r for r in rows
            if (not k or (k in r["nickname"].lower() or k in r["device_id"].lower()))
            and (not tc or r["team_code"] == tc)
        ]
    total = len(rows)
    items = rows[(page - 1) * page_size : page * page_size]
    return {"total": total, "items": items, "summary": summary}


@router.get("/{batch_id}/export")
def export_task_contributors(
    batch_id: int,
    keyword: str | None = None,
    team_code: str | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """导出该任务的发音人贡献 CSV（全量，遵循 keyword/team_code 筛选）。"""
    _get_task(db, admin, batch_id)
    rows = _task_contributor_rows(db, batch_id)
    k = (keyword or "").strip().lower()
    tc = _normalize(team_code) if team_code else None
    if k or tc:
        rows = [
            r for r in rows
            if (not k or (k in r["nickname"].lower() or k in r["device_id"].lower()))
            and (not tc or r["team_code"] == tc)
        ]
    columns = [
        "发音人ID", "昵称", "设备ID", "团队码", "团队名", "省份", "城市", "区县",
        "录音总数", "待审核数", "通过数", "驳回数",
        "总时长_ms", "有效时长_ms", "无效时长_ms", "通过率", "最近提交时间",
    ]
    out = []
    for r in rows:
        out.append({
            "发音人ID": r["speaker_id"],
            "昵称": r["nickname"],
            "设备ID": r["device_id"],
            "团队码": r["team_code"],
            "团队名": r["team_name"],
            "省份": r["province_name"],
            "城市": r["city_name"],
            "区县": r["district_name"],
            "录音总数": r["recording_total"],
            "待审核数": r["pending"],
            "通过数": r["approved"],
            "驳回数": r["rejected"],
            "总时长_ms": r["total_duration_ms"],
            "有效时长_ms": r["valid_duration_ms"],
            "无效时长_ms": r["invalid_duration_ms"],
            "通过率": r["approval_rate"],
            "最近提交时间": r["last_active"].strftime("%Y-%m-%d %H:%M:%S")
            if r["last_active"] else "",
        })
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return csv_response(out, columns, f"task_{batch_id}_{ts}.csv")


@router.get("/{batch_id}/words", response_model=list[WordOut])
def task_words(
    batch_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """任务包含的词条清单（按加入顺序）。occupied = 被其他非关闭任务占用（排除本任务自身），
    供「从任务带入词条」跳过已占用、以及编辑草稿时标注相对其他任务的占用。"""
    _get_task(db, admin, batch_id)
    words = (
        db.query(WordLibrary)
        .join(TaskBatchItem, TaskBatchItem.word_id == WordLibrary.id)
        .filter(TaskBatchItem.task_batch_id == batch_id)
        .order_by(TaskBatchItem.id)
        .all()
    )
    occ_q = (
        db.query(TaskBatchItem.word_id)
        .join(TaskBatch, TaskBatch.id == TaskBatchItem.task_batch_id)
        .filter(TaskBatch.status.in_(["draft", "published"]))
        .filter(TaskBatchItem.task_batch_id != batch_id)
    )
    occupied_ids = {r[0] for r in occ_q.all()}
    out = []
    for w in words:
        o = WordOut.model_validate(w)
        o.occupied = w.id in occupied_ids
        out.append(o)
    return out


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
    if "deadline_at" in data:
        # 截止时间可设/可清空（传 null 即清空）；exclude_unset 已区分「未传」与「传 null」
        batch.deadline_at = data["deadline_at"]
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


@router.post("/cleanup-expired")
def cleanup_expired_tasks(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """一键清理到期任务（后台完善 9）：关闭所有「已发布且已过截止时间」的任务。

    关闭后小程序端立即不再展示/采录（mp 校验 status=published）；省管理员只清理本省。
    """
    q = db.query(TaskBatch).filter(
        TaskBatch.status == "published",
        TaskBatch.deadline_at.isnot(None),
        TaskBatch.deadline_at < datetime.now(timezone.utc),
    )
    if admin.role == "province_admin" and admin.province_code:
        q = q.filter(TaskBatch.province_code == admin.province_code)
    batches = q.all()
    for b in batches:
        b.status = "closed"
        log_admin_action(
            db, admin, "到期自动关闭", "task", b.id,
            summary=f"到期自动关闭任务 #{b.id}「{b.name}」",
            ip=rate_limit.client_ip(request),
        )
    db.commit()
    return {"closed": len(batches)}


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
