"""管理后台数据看板（阶段十二）。

平台/本省整体概览 + 每个发音人的详细数据（每发音人一行关键指标 + 下钻领取记录）。
权限：超管看全国，省管理员仅看本省（沿用 speakers.py 的属地钳制与聚合模式）。
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.deps import get_current_admin
from ..core.reject_reasons import LABELS as REJECT_REASON_LABELS
from ..core.speaker_quality import warning_state
from ..db import get_db
from ..models.admin import AdminUser
from ..models.recording import Recording
from ..models.region import Region
from ..models.speaker import Speaker
from ..models.task import TaskBatch
from ..models.task_claim import TaskClaim
from ..models.word import WordLibrary
from ..schemas.dashboard import (
    DashboardClaimOut,
    DashboardRejectionReasons,
    DashboardSpeakerRow,
    DashboardSummary,
    DashboardTrends,
    DashboardWordDifficulty,
    RejectionReasonRow,
    RegionBreakdownItem,
)
from .speakers import AGE_BRACKETS, GENDERS, _speaker_query

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

VALID_SORTS = {"recording", "approved", "duration", "last_active", "created"}
VALID_WORD_SORTS = {"reject", "approval", "recording"}


def _validate_dashboard_filters(gender, age_bracket, sort_by):
    if gender is not None and gender not in GENDERS:
        raise HTTPException(status_code=422, detail="gender 仅支持 male/female/other")
    if age_bracket is not None and age_bracket not in AGE_BRACKETS:
        raise HTTPException(status_code=422, detail="age_bracket 仅支持 under18/age18_30/age31_45/age46_60/over60")
    if sort_by not in VALID_SORTS:
        raise HTTPException(status_code=422, detail="sort_by 仅支持 recording/approved/duration/last_active/created")


def _province_scope(db: Session, admin: AdminUser) -> str | None:
    """省管理员返回本省 code，超管返回 None（全国）。"""
    if admin.role == "province_admin" and admin.province_code:
        return admin.province_code
    return None


def _scoped_speaker_query(db: Session, scope: str | None):
    q = db.query(Speaker)
    if scope:
        q = q.filter(Speaker.province_code == scope)
    return q


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """平台/本省概览：发音人/录音/审核/时长/通过率/活跃任务/团队/已录词条 + 区域分布。"""
    scope = _province_scope(db, admin)
    sp_q = _scoped_speaker_query(db, scope)

    speaker_total = sp_q.count()
    team_total = (
        sp_q.with_entities(Speaker.team_code)
        .filter(Speaker.team_code.isnot(None))
        .distinct()
        .count()
    )

    # 录音聚合（join Speaker 按属地钳制）
    rec_q = db.query(Recording).join(Speaker, Recording.speaker_id == Speaker.id)
    if scope:
        rec_q = rec_q.filter(Speaker.province_code == scope)
    status_rows = (
        rec_q.with_entities(
            Recording.status, func.count(Recording.id), func.sum(Recording.audio_duration)
        )
        .group_by(Recording.status)
        .all()
    )
    counts = {s: {"cnt": c, "dur": d or 0} for s, c, d in status_rows}
    pending = counts.get("pending", {}).get("cnt", 0)
    approved = counts.get("approved", {}).get("cnt", 0)
    rejected = counts.get("rejected", {}).get("cnt", 0)
    recording_total = pending + approved + rejected
    approved_duration_ms = counts.get("approved", {}).get("dur", 0)
    approval_rate = approved / (approved + rejected) if (approved + rejected) else 0.0

    distinct_word_total = (
        rec_q.with_entities(func.count(func.distinct(Recording.word_id))).scalar() or 0
    )

    task_q = db.query(TaskBatch).filter(TaskBatch.status == "published")
    if scope:
        task_q = task_q.filter(TaskBatch.province_code == scope)
    active_task_total = task_q.count()

    # 区域分布：超管按省分组、省管理员按本省市级分组
    group_col = Speaker.city_code if scope else Speaker.province_code
    sp_by_region = dict(
        sp_q.with_entities(group_col, func.count(Speaker.id)).group_by(group_col).all()
    )
    rec_by_region = dict(
        db.query(group_col, func.count(Recording.id))
        .join(Recording, Recording.speaker_id == Speaker.id)
        .filter(Recording.speaker_id.isnot(None))
        .group_by(group_col)
        .all()
    )
    region_names = {
        r.code: r.name
        for r in db.query(Region).filter(Region.code.in_([c for c in sp_by_region if c])).all()
    }
    region_breakdown = [
        RegionBreakdownItem(
            code=code,
            name=region_names.get(code, code),
            speaker_total=sp_by_region[code],
            recording_total=rec_by_region.get(code, 0),
        )
        for code in sp_by_region
        if code
    ]
    region_breakdown.sort(key=lambda x: x.name)

    return DashboardSummary(
        speaker_total=speaker_total,
        recording_total=recording_total,
        pending=pending,
        approved=approved,
        rejected=rejected,
        total_duration_ms=sum(v["dur"] for v in counts.values()),
        approved_duration_ms=approved_duration_ms,
        approval_rate=approval_rate,
        active_task_total=active_task_total,
        team_total=team_total,
        distinct_word_total=distinct_word_total,
        region_breakdown=region_breakdown,
    )


@router.get("/speakers")
def dashboard_speakers(
    keyword: str | None = None,
    province_code: str | None = None,
    gender: str | None = None,
    age_bracket: str | None = None,
    team_code: str | None = None,
    sort_by: str = "recording",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """每个发音人一行关键指标（录音/审核/时长/通过率/任务数/词条数/最近活跃）。"""
    _validate_dashboard_filters(gender, age_bracket, sort_by)
    q = _speaker_query(db, admin, keyword, province_code, gender, age_bracket)
    if team_code:
        q = q.filter(Speaker.team_code == team_code.strip().upper())

    all_ids = [s.id for s in q.all()]
    if not all_ids:
        return {"total": 0, "items": []}

    # —— 一次性聚合（先算全体再分页排序，保证排序/分页正确）——
    dur_rows = (
        db.query(
            Recording.speaker_id, Recording.status, func.count(Recording.id),
            func.sum(Recording.audio_duration),
        )
        .filter(Recording.speaker_id.in_(all_ids))
        .group_by(Recording.speaker_id, Recording.status)
        .all()
    )
    dur_map = {(sid, st): (c, d or 0) for sid, st, c, d in dur_rows}
    task_cnt = dict(
        db.query(Recording.speaker_id, func.count(func.distinct(Recording.task_id)))
        .filter(Recording.speaker_id.in_(all_ids))
        .group_by(Recording.speaker_id)
        .all()
    )
    word_cnt = dict(
        db.query(Recording.speaker_id, func.count(func.distinct(Recording.word_id)))
        .filter(Recording.speaker_id.in_(all_ids))
        .group_by(Recording.speaker_id)
        .all()
    )
    last_active = dict(
        db.query(Recording.speaker_id, func.max(Recording.created_at))
        .filter(Recording.speaker_id.in_(all_ids))
        .group_by(Recording.speaker_id)
        .all()
    )
    created_map = dict(
        db.query(Speaker.id, Speaker.created_at)
        .filter(Speaker.id.in_(all_ids))
        .all()
    )

    def _pick(sid, st):
        return dur_map.get((sid, st), (0, 0))

    # 汇总为可排序的中间行
    rows = []
    for sid in all_ids:
        pending_c, pending_d = _pick(sid, "pending")
        approved_c, approved_d = _pick(sid, "approved")
        rejected_c, rejected_d = _pick(sid, "rejected")
        rows.append({
            "sid": sid,
            "pending": pending_c,
            "approved": approved_c,
            "rejected": rejected_c,
            "recording_total": pending_c + approved_c + rejected_c,
            "duration": pending_d + approved_d + rejected_d,
            "approved_duration": approved_d,
            "last_active": last_active.get(sid),
            "created": created_map.get(sid),
        })

    # 排序（Python 层：聚合指标无法直接在 SQL 排序；空 last_active 排末尾）
    def _ts(x):
        return x.timestamp() if x else 0

    if sort_by == "approved":
        rows.sort(key=lambda x: (-x["approved"], -x["sid"]))
    elif sort_by == "duration":
        rows.sort(key=lambda x: (-x["duration"], -x["sid"]))
    elif sort_by == "last_active":
        rows.sort(key=lambda x: (x["last_active"] is None, -_ts(x["last_active"]), -x["sid"]))
    elif sort_by == "created":
        rows.sort(key=lambda x: (-_ts(x["created"]), -x["sid"]))
    else:  # recording
        rows.sort(key=lambda x: (-x["recording_total"], -x["sid"]))

    total = len(all_ids)
    page_ids = [r["sid"] for r in rows[(page - 1) * page_size : page * page_size]]
    if not page_ids:
        return {"total": total, "items": []}

    # 按 id 取当前页发音人（顺序以 page_ids 为准）
    speaker_map = {s.id: s for s in db.query(Speaker).filter(Speaker.id.in_(page_ids)).all()}
    items = []
    for sid in page_ids:
        s = speaker_map[sid]
        dur_row = next(r for r in rows if r["sid"] == sid)
        approved = dur_row["approved"]
        rejected = dur_row["rejected"]
        quality_warned, _, _ = warning_state(approved, rejected)
        items.append(
            DashboardSpeakerRow(
                id=s.id,
                openid=s.openid,
                device_id=s.device_id,
                nickname=s.nickname,
                province_code=s.province_code,
                city_code=s.city_code,
                team_code=s.team_code,
                gender=s.gender,
                age_bracket=s.age_bracket,
                created_at=s.created_at,
                recording_total=dur_row["recording_total"],
                pending=dur_row["pending"],
                approved=approved,
                rejected=rejected,
                total_duration_ms=dur_row["duration"],
                approved_duration_ms=dur_row["approved_duration"],
                approval_rate=approved / (approved + rejected)
                if (approved + rejected)
                else 0.0,
                upload_paused=s.upload_paused,
                quality_warned=quality_warned,
                task_count=task_cnt.get(sid, 0),
                word_count=word_cnt.get(sid, 0),
                last_active_at=dur_row["last_active"],
            )
        )
    return {"total": total, "items": items}


@router.get("/trends", response_model=DashboardTrends)
def dashboard_trends(
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """近 days 天新增录音/审核趋势（数字卡片）。窗口边界在 Python 端取 UTC，避免时区不一致。"""
    scope = _province_scope(db, admin)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rec_q = db.query(Recording).join(Speaker, Recording.speaker_id == Speaker.id)
    if scope:
        rec_q = rec_q.filter(Speaker.province_code == scope)
    rec_q = rec_q.filter(Recording.created_at >= cutoff)
    rows = (
        rec_q.with_entities(Recording.status, func.count(Recording.id))
        .group_by(Recording.status)
        .all()
    )
    counts = {s: c for s, c in rows}
    pending = counts.get("pending", 0)
    approved = counts.get("approved", 0)
    rejected = counts.get("rejected", 0)
    return DashboardTrends(
        days=days,
        new_recordings=pending + approved + rejected,
        pending=pending,
        approved=approved,
        rejected=rejected,
        approval_rate=approved / (approved + rejected) if (approved + rejected) else 0.0,
    )


@router.get("/words")
def dashboard_words(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    sort_by: str = "reject",
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """词条采集难度快照：按词条聚合录音状态（通过/驳回/待审），默认驳回多优先。

    省管理员仅统计本省词条。无审核历史表，用当前 rejected 计数近似「反复被驳回」。
    """
    if sort_by not in VALID_WORD_SORTS:
        raise HTTPException(status_code=422, detail="sort_by 仅支持 reject/approval/recording")

    word_q = db.query(WordLibrary)
    if admin.role == "province_admin" and admin.province_code:
        word_q = word_q.filter(WordLibrary.province_code == admin.province_code)
    words = word_q.all()
    if not words:
        return {"total": 0, "items": []}
    word_ids = [w.id for w in words]

    rows = (
        db.query(Recording.word_id, Recording.status, func.count(Recording.id))
        .filter(Recording.word_id.in_(word_ids))
        .group_by(Recording.word_id, Recording.status)
        .all()
    )
    agg: dict[int, dict] = {}
    for wid, st, c in rows:
        d = agg.setdefault(wid, {"pending": 0, "approved": 0, "rejected": 0})
        d[st] = c

    items = []
    for w in words:
        a = agg.get(w.id, {"pending": 0, "approved": 0, "rejected": 0})
        reviewed = a["approved"] + a["rejected"]
        items.append(
            DashboardWordDifficulty(
                word_id=w.id,
                code=w.code,
                content=w.content,
                dialect_point=w.dialect_point,
                province_code=w.province_code,
                recording_total=a["pending"] + a["approved"] + a["rejected"],
                pending=a["pending"],
                approved=a["approved"],
                rejected=a["rejected"],
                approval_rate=a["approved"] / reviewed if reviewed else 0.0,
                reject_rate=a["rejected"] / reviewed if reviewed else 0.0,
            )
        )
    if sort_by == "approval":
        items.sort(key=lambda x: (x.approval_rate, -x.rejected, -x.word_id))
    elif sort_by == "recording":
        items.sort(key=lambda x: (-x.recording_total, -x.word_id))
    else:  # reject：驳回多优先，同量按驳回率
        items.sort(key=lambda x: (-x.rejected, -x.reject_rate, -x.word_id))

    total = len(items)
    page_items = items[(page - 1) * page_size : page * page_size]
    return {"total": total, "items": page_items}


@router.get("/speakers/{speaker_id}/claims", response_model=list[DashboardClaimOut])
def dashboard_speaker_claims(
    speaker_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """单发音人的领取记录（词条 + 任务 + 是否已录）。"""
    speaker = db.get(Speaker, speaker_id)
    if speaker is None:
        raise HTTPException(status_code=404, detail="发音人不存在")
    if (
        admin.role == "province_admin"
        and admin.province_code
        and speaker.province_code != admin.province_code
    ):
        raise HTTPException(status_code=403, detail="只能查看本省发音人")

    claims = (
        db.query(TaskClaim)
        .filter(TaskClaim.speaker_id == speaker_id)
        .order_by(TaskClaim.claimed_at.desc(), TaskClaim.id.desc())
        .all()
    )
    if not claims:
        return []
    task_ids = {c.task_id for c in claims}
    word_ids = {c.word_id for c in claims}
    task_map = {t.id: t for t in db.query(TaskBatch).filter(TaskBatch.id.in_(task_ids)).all()}
    word_map = {w.id: w for w in db.query(WordLibrary).filter(WordLibrary.id.in_(word_ids)).all()}
    recorded_keys = {
        (r.task_id, r.word_id)
        for r in db.query(Recording.task_id, Recording.word_id)
        .filter(
            Recording.speaker_id == speaker_id,
            Recording.task_id.in_(task_ids),
            Recording.word_id.in_(word_ids),
        )
        .all()
    }
    return [
        DashboardClaimOut(
            claim_id=c.id,
            task_id=c.task_id,
            task_name=task_map[c.task_id].name if c.task_id in task_map else f"任务#{c.task_id}",
            word_id=c.word_id,
            word_code=word_map[c.word_id].code if c.word_id in word_map else None,
            word_content=word_map[c.word_id].content if c.word_id in word_map else f"词条#{c.word_id}",
            recorded=(c.task_id, c.word_id) in recorded_keys,
            claimed_at=c.claimed_at,
        )
        for c in claims
    ]


@router.get("/rejection-reasons", response_model=DashboardRejectionReasons)
def dashboard_rejection_reasons(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """驳回原因分布：按固定原因聚合被驳回录音数，反哺任务投放。

    reject_reasons 是逗号连接的多选 key → 不能 group_by，Python 端拆串计数；
    NULL（旧数据或驳回时未选原因）计入「未标注」。省管理员钳制为本省。
    """
    scope = _province_scope(db, admin)
    rec_q = db.query(Recording).join(Speaker, Recording.speaker_id == Speaker.id)
    if scope:
        rec_q = rec_q.filter(Speaker.province_code == scope)
    reason_rows = (
        rec_q.filter(Recording.status == "rejected")
        .with_entities(Recording.reject_reasons)
        .all()
    )

    counts: dict[str, int] = {}
    for (r,) in reason_rows:
        if r:  # 一条录音可能多选，逗号拆开逐个计数
            for k in r.split(","):
                counts[k] = counts.get(k, 0) + 1
        else:
            counts["unknown"] = counts.get("unknown", 0) + 1

    def _label(k: str) -> str:
        if k == "unknown":
            return "未标注"
        return REJECT_REASON_LABELS.get(k, k)

    items = [
        RejectionReasonRow(reason=k, label=_label(k), count=c)
        for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return DashboardRejectionReasons(total=len(reason_rows), items=items)
