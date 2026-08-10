"""发音人管理（管理后台，阶段六）。

管理员分页查看/筛选发音人，编辑发音人画像（性别/年龄段），查看单个发音人的
录音明细（分页列表 + 审核状态分布/贡献统计）。省管理员仅能看/改本省发音人，
超管看全国。
"""
import csv
import io
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..core.deps import get_current_admin
from ..db import get_db
from ..models.admin import AdminUser
from ..models.recording import Recording
from ..models.region import Region
from ..models.speaker import Speaker
from ..models.task import TaskBatch
from ..models.word import WordLibrary
from ..schemas.speakers import (
    SpeakerAdminOut,
    SpeakerRecordingOut,
    SpeakerRecordingStats,
    SpeakerRecordingsOut,
    SpeakerTaskStat,
    SpeakerUpdate,
)
from ..services import storage
from .mp import AGE_BRACKETS, GENDERS

router = APIRouter(prefix="/api/speakers", tags=["speakers"])

VALID_REC_STATUS = {"pending", "approved", "rejected"}

GENDER_LABELS = {"male": "男", "female": "女", "other": "其他"}
AGE_BRACKET_LABELS = {
    "under18": "<18",
    "age18_30": "18-30",
    "age31_45": "31-45",
    "age46_60": "46-60",
    "over60": ">60",
}
STATUS_LABELS = {"pending": "待审核", "approved": "已通过", "rejected": "已驳回"}


def _validate_filters(gender: str | None, age_bracket: str | None) -> None:
    if gender is not None and gender not in GENDERS:
        raise HTTPException(status_code=422, detail="gender 仅支持 male/female/other")
    if age_bracket is not None and age_bracket not in AGE_BRACKETS:
        raise HTTPException(status_code=422, detail="age_bracket 仅支持 under18/age18_30/age31_45/age46_60/over60")


def _speaker_query(
    db: Session,
    admin: AdminUser,
    keyword: str | None = None,
    province_code: str | None = None,
    gender: str | None = None,
    age_bracket: str | None = None,
):
    """发音人列表/导出的共享筛选查询。省管理员仅能看本省。"""
    q = db.query(Speaker)
    if admin.role == "province_admin" and admin.province_code:
        q = q.filter(Speaker.province_code == admin.province_code)
    if province_code:
        q = q.filter(Speaker.province_code == province_code)
    if gender:
        q = q.filter(Speaker.gender == gender)
    if age_bracket:
        q = q.filter(Speaker.age_bracket == age_bracket)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                Speaker.nickname.like(like),
                Speaker.device_id.like(like),
                Speaker.openid.like(like),
            )
        )
    return q


def _recording_duration_map(db: Session) -> dict[tuple[int, str], tuple[int, int]]:
    """发音人 × 状态的 (录音数, 总时长) 聚合，(speaker_id, status) → (cnt, dur_ms)。"""
    rows = (
        db.query(
            Recording.speaker_id,
            Recording.status,
            func.count(Recording.id),
            func.sum(Recording.audio_duration),
        )
        .group_by(Recording.speaker_id, Recording.status)
        .all()
    )
    return {(sid, st): (cnt, dur or 0) for sid, st, cnt, dur in rows}


def _csv_response(rows: list[dict], columns: list[str], fname: str) -> Response:
    """utf-8-sig CSV 下载响应（Excel 双击可直接打开中文）。"""
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=text.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"; filename*=UTF-8\'\'{quote(fname)}'
        },
    )


def _recording_counts(db: Session) -> dict[int, int]:
    """每个发音人的录音数（speaker_id → count）。"""
    rows = (
        db.query(Recording.speaker_id, func.count(Recording.id))
        .group_by(Recording.speaker_id)
        .all()
    )
    return {sid: cnt for sid, cnt in rows}


def _to_out(speaker: Speaker, counts: dict[int, int]) -> SpeakerAdminOut:
    out = SpeakerAdminOut.model_validate(speaker)
    out.recording_count = counts.get(speaker.id, 0)
    return out


@router.get("")
def list_speakers(
    keyword: str | None = None,
    province_code: str | None = None,
    gender: str | None = None,
    age_bracket: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """分页列出发音人，可按省份/关键词/性别/年龄段筛选。"""
    _validate_filters(gender, age_bracket)
    q = _speaker_query(db, admin, keyword, province_code, gender, age_bracket)

    total = q.count()
    speakers = (
        q.order_by(Speaker.created_at.desc(), Speaker.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    counts = _recording_counts(db)
    items = [_to_out(s, counts) for s in speakers]
    return {"total": total, "items": items}


@router.get("/export")
def export_speakers_durations(
    keyword: str | None = None,
    province_code: str | None = None,
    gender: str | None = None,
    age_bracket: str | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """导出发音人时长汇总 CSV（全量，不受分页影响，遵循当前筛选）。

    每个发音人一行：录音数 + 总时长 / 有效时长（审核通过）/ 无效时长（驳回）。
    时长单位为毫秒（与系统内 audio_duration 一致，无舍入误差）。
    """
    _validate_filters(gender, age_bracket)
    speakers = _speaker_query(db, admin, keyword, province_code, gender, age_bracket).all()
    dur_map = _recording_duration_map(db)
    region_names = {
        r.code: r.name for r in db.query(Region).filter(Region.level == 1).all()
    }

    columns = [
        "发音人ID",
        "昵称",
        "设备ID",
        "省份",
        "性别",
        "年龄段",
        "录音总数",
        "待审核数",
        "通过数",
        "驳回数",
        "总时长_ms",
        "有效时长_ms",
        "无效时长_ms",
    ]
    rows = []
    for sp in speakers:
        def _agg(status):
            return dur_map.get((sp.id, status), (0, 0))

        pending_cnt, pending_dur = _agg("pending")
        approved_cnt, approved_dur = _agg("approved")
        rejected_cnt, rejected_dur = _agg("rejected")
        rows.append(
            {
                "发音人ID": sp.id,
                "昵称": sp.nickname or "",
                "设备ID": sp.device_id or "",
                "省份": region_names.get(sp.province_code, sp.province_code or ""),
                "性别": GENDER_LABELS.get(sp.gender, sp.gender or ""),
                "年龄段": AGE_BRACKET_LABELS.get(sp.age_bracket, sp.age_bracket or ""),
                "录音总数": pending_cnt + approved_cnt + rejected_cnt,
                "待审核数": pending_cnt,
                "通过数": approved_cnt,
                "驳回数": rejected_cnt,
                "总时长_ms": pending_dur + approved_dur + rejected_dur,
                "有效时长_ms": approved_dur,
                "无效时长_ms": rejected_dur,
            }
        )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return _csv_response(rows, columns, f"speakers_duration_{ts}.csv")


@router.patch("/{speaker_id}", response_model=SpeakerAdminOut)
def update_speaker_profile(
    speaker_id: int,
    body: SpeakerUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """编辑发音人画像/属地（纠错）：缺省不改，null/空串清空，非法值 422。

    属地可改省+市；改动后清空 team_code（原绑定作废，可重新绑定/后台重定属地）。
    省管理员只能改本省发音人、且不能把属地移出本省。
    """
    speaker = db.get(Speaker, speaker_id)
    if speaker is None:
        raise HTTPException(status_code=404, detail="发音人不存在")

    if (
        admin.role == "province_admin"
        and admin.province_code
        and speaker.province_code
        and speaker.province_code != admin.province_code
    ):
        raise HTTPException(status_code=403, detail="只能操作本省发音人")

    data = body.model_dump(exclude_unset=True)
    gender = data.get("gender")
    age_bracket = data.get("age_bracket")
    if gender is not None and gender != "" and gender not in GENDERS:
        raise HTTPException(status_code=422, detail="gender 仅支持 male/female/other")
    if age_bracket is not None and age_bracket != "" and age_bracket not in AGE_BRACKETS:
        raise HTTPException(status_code=422, detail="age_bracket 仅支持 under18/age18_30/age31_45/age46_60/over60")

    if "gender" in data:
        speaker.gender = gender or None
    if "age_bracket" in data:
        speaker.age_bracket = age_bracket or None

    # —— 属地纠错（省+市）——
    new_province = data.get("province_code") if "province_code" in data else None
    if new_province is not None:
        new_province = new_province or None
        if new_province:
            province = db.get(Region, new_province)
            if province is None or province.level != 1:
                raise HTTPException(status_code=422, detail="province_code 无效，须为有效省级代码")
        if (
            admin.role == "province_admin"
            and admin.province_code
            and new_province != admin.province_code
        ):
            raise HTTPException(status_code=403, detail="省管理员不能把属地改到本省之外")

    new_city = data.get("city_code") if "city_code" in data else None
    if new_city is not None:
        new_city = new_city or None
        base_province = new_province if new_province is not None else speaker.province_code
        if new_city:
            city = db.get(Region, new_city)
            if city is None or city.level != 2 or city.parent_code != base_province:
                raise HTTPException(status_code=422, detail="city_code 无效，须为归属该省的市级代码")

    province_changed = "province_code" in data and new_province != speaker.province_code
    city_changed = "city_code" in data and new_city != speaker.city_code
    if province_changed:
        speaker.province_code = new_province
    if city_changed:
        speaker.city_code = new_city
    if province_changed or city_changed:
        # 属地被改动 → 原团队码绑定作废
        speaker.team_code = None

    db.commit()
    db.refresh(speaker)
    return _to_out(speaker, _recording_counts(db))


def _recording_out(rec: Recording, db: Session) -> SpeakerRecordingOut:
    """把一条录音富化成明细列表项（含任务名/词条信息）。"""
    task = db.get(TaskBatch, rec.task_id)
    word = db.get(WordLibrary, rec.word_id)
    return SpeakerRecordingOut(
        id=rec.id,
        task_id=rec.task_id,
        task_name=task.name if task else f"任务#{rec.task_id}",
        word_id=rec.word_id,
        word_code=word.code if word else None,
        word_content=word.content if word else f"词条#{rec.word_id}",
        status=rec.status,
        audio_url=storage.play_url(rec.audio_url),  # COS→预签名；本地→相对路径
        audio_duration=rec.audio_duration,
        file_size=rec.file_size,
        review_note=rec.review_note,
        reviewed_at=rec.reviewed_at,
        created_at=rec.created_at,
    )


def _speaker_stats(db: Session, speaker_id: int) -> SpeakerRecordingStats:
    """发音人录音贡献统计（全量，不受列表筛选影响）。"""
    rows = (
        db.query(
            Recording.status,
            func.count(Recording.id),
            func.sum(Recording.audio_duration),
        )
        .filter(Recording.speaker_id == speaker_id)
        .group_by(Recording.status)
        .all()
    )
    counts = {s: {"cnt": c, "dur": d or 0} for s, c, d in rows}
    pending = counts.get("pending", {}).get("cnt", 0)
    approved = counts.get("approved", {}).get("cnt", 0)
    rejected = counts.get("rejected", {}).get("cnt", 0)
    total_duration = sum(v["dur"] for v in counts.values())

    task_rows = (
        db.query(Recording.task_id, func.count(Recording.id))
        .filter(Recording.speaker_id == speaker_id)
        .group_by(Recording.task_id)
        .all()
    )
    tasks = []
    for tid, cnt in task_rows:
        t = db.get(TaskBatch, tid)
        tasks.append(
            SpeakerTaskStat(
                task_id=tid, task_name=t.name if t else f"任务#{tid}", count=cnt
            )
        )
    tasks.sort(key=lambda x: -x.count)
    return SpeakerRecordingStats(
        total=pending + approved + rejected,
        pending=pending,
        approved=approved,
        rejected=rejected,
        total_duration_ms=total_duration,
        approved_duration_ms=counts.get("approved", {}).get("dur", 0),
        rejected_duration_ms=counts.get("rejected", {}).get("dur", 0),
        tasks=tasks,
    )


@router.get("/{speaker_id}/recordings", response_model=SpeakerRecordingsOut)
def speaker_recordings(
    speaker_id: int,
    status: str | None = None,
    task_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """单个发音人的录音明细：分页列表（可按任务/状态筛选）+ 贡献统计。"""
    speaker = db.get(Speaker, speaker_id)
    if speaker is None:
        raise HTTPException(status_code=404, detail="发音人不存在")

    if (
        admin.role == "province_admin"
        and admin.province_code
        and speaker.province_code != admin.province_code
    ):
        raise HTTPException(status_code=403, detail="只能查看本省发音人")

    if status is not None and status not in VALID_REC_STATUS:
        raise HTTPException(status_code=422, detail="status 仅支持 pending/approved/rejected")

    q = db.query(Recording).filter(Recording.speaker_id == speaker_id)
    if task_id is not None:
        q = q.filter(Recording.task_id == task_id)
    if status is not None:
        q = q.filter(Recording.status == status)

    total = q.count()
    recs = (
        q.order_by(Recording.created_at.desc(), Recording.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [_recording_out(r, db) for r in recs]
    return SpeakerRecordingsOut(
        speaker_id=speaker_id,
        total=total,
        items=items,
        stats=_speaker_stats(db, speaker_id),
    )


@router.get("/{speaker_id}/recordings/export")
def export_speaker_recordings(
    speaker_id: int,
    status: str | None = None,
    task_id: int | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """导出发音人录音明细 CSV（全量，不受分页影响，遵循状态/任务筛选）。"""
    speaker = db.get(Speaker, speaker_id)
    if speaker is None:
        raise HTTPException(status_code=404, detail="发音人不存在")
    if (
        admin.role == "province_admin"
        and admin.province_code
        and speaker.province_code != admin.province_code
    ):
        raise HTTPException(status_code=403, detail="只能查看本省发音人")
    if status is not None and status not in VALID_REC_STATUS:
        raise HTTPException(status_code=422, detail="status 仅支持 pending/approved/rejected")

    q = db.query(Recording).filter(Recording.speaker_id == speaker_id)
    if task_id is not None:
        q = q.filter(Recording.task_id == task_id)
    if status is not None:
        q = q.filter(Recording.status == status)
    recs = q.order_by(Recording.created_at.desc(), Recording.id.desc()).all()

    columns = [
        "录音ID",
        "任务",
        "词条编码",
        "词条内容",
        "状态",
        "时长_ms",
        "文件大小_B",
        "审核备注",
        "审核时间",
        "提交时间",
        "音频路径",
    ]
    rows = []
    for r in recs:
        out = _recording_out(r, db)
        rows.append(
            {
                "录音ID": r.id,
                "任务": out.task_name,
                "词条编码": out.word_code or "",
                "词条内容": out.word_content,
                "状态": STATUS_LABELS.get(r.status, r.status),
                "时长_ms": r.audio_duration,
                "文件大小_B": r.file_size,
                "审核备注": out.review_note or "",
                "审核时间": out.reviewed_at.isoformat() if out.reviewed_at else "",
                "提交时间": out.created_at.isoformat() if out.created_at else "",
                "音频路径": r.audio_url,  # 逻辑路径（不导出会过期的预签名 URL）
            }
        )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return _csv_response(rows, columns, f"speaker_{speaker_id}_recordings_{ts}.csv")
