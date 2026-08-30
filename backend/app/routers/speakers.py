"""发音人管理（管理后台，阶段六）。

管理员分页查看/筛选发音人，编辑发音人画像（性别/年龄段），查看单个发音人的
录音明细（分页列表 + 审核状态分布/贡献统计）。省管理员仅能看/改本省发音人，
超管看全国。
"""
import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.deps import get_current_admin
from ..core.speaker_quality import warning_state
from ..db import get_db
from ..models.admin import AdminUser
from ..models.agreement import SpeakerAgreement
from ..models.recording import Recording
from ..models.region import Region
from ..models.speaker import Speaker
from ..models.task import TaskBatch
from ..models.task_claim import TaskClaim
from ..models.word import WordLibrary
from ..schemas.speakers import (
    SpeakerAdminOut,
    SpeakerMergeRequest,
    SpeakerRecordingOut,
    SpeakerRecordingStats,
    SpeakerRecordingsOut,
    SpeakerTaskStat,
    SpeakerUpdate,
)
from ..services import rate_limit, storage
from ..services.audit import log_admin_action
from ..services.export import recordings_zip_response
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


def _review_counts(db: Session) -> dict[int, tuple[int, int]]:
    """每个发音人的已审核计数（speaker_id → (approved, rejected)）。

    与看板 dashboard_speakers 同口径：只统计已审核（通过+驳回），pending 不计入通过率。
    """
    rows = (
        db.query(Recording.speaker_id, Recording.status, func.count(Recording.id))
        .filter(Recording.status.in_(["approved", "rejected"]))
        .group_by(Recording.speaker_id, Recording.status)
        .all()
    )
    out: dict[int, list[int]] = {}
    for sid, st, cnt in rows:
        d = out.setdefault(sid, [0, 0])
        d[0 if st == "approved" else 1] += cnt
    return {sid: (a, r) for sid, (a, r) in out.items()}


def _pick_better_recording(a: Recording, b: Recording) -> Recording:
    """录音冲突保留策略：approved > rejected > pending，同级保留 created_at 较新者。

    返回应保留的录音，调用方删除另一个（并清理其存储对象）。词条/发音人合并共用。
    """
    priority = {"approved": 0, "rejected": 1, "pending": 2}
    pa = priority.get(a.status, 9)
    pb = priority.get(b.status, 9)
    if pb < pa:
        return b
    if pb > pa:
        return a
    ta = a.created_at or a.id
    tb = b.created_at or b.id
    return b if tb > ta else a


def _to_out(
    speaker: Speaker,
    counts: dict[int, int],
    review_counts: dict[int, tuple[int, int]],
) -> SpeakerAdminOut:
    out = SpeakerAdminOut.model_validate(speaker)
    out.recording_count = counts.get(speaker.id, 0)
    approved, rejected = review_counts.get(speaker.id, (0, 0))
    out.quality_warned, out.approval_rate, out.reviewed_total = warning_state(
        approved, rejected
    )
    return out


@router.get("")
def list_speakers(
    keyword: str | None = None,
    province_code: str | None = None,
    gender: str | None = None,
    age_bracket: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
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
    review_counts = _review_counts(db)
    items = [_to_out(s, counts, review_counts) for s in speakers]
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

    # —— 质量预警：一键暂停/恢复上传（后台完善 3，缺省不改）——
    if "upload_paused" in data and data["upload_paused"] is not None:
        speaker.upload_paused = bool(data["upload_paused"])

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

    new_district = data.get("district_code") if "district_code" in data else None
    if new_district is not None:
        new_district = new_district or None
        base_city = new_city if new_city is not None else speaker.city_code
        if new_district:
            district = db.get(Region, new_district)
            if district is None or district.level != 3 or district.parent_code != base_city:
                raise HTTPException(status_code=422, detail="district_code 无效，须为归属该市的区县级代码")

    province_changed = "province_code" in data and new_province != speaker.province_code
    city_changed = "city_code" in data and new_city != speaker.city_code
    district_changed = "district_code" in data and new_district != speaker.district_code
    if province_changed:
        speaker.province_code = new_province
    if city_changed:
        speaker.city_code = new_city
    if district_changed:
        speaker.district_code = new_district
    if province_changed or city_changed or district_changed:
        # 属地被改动 → 原团队码绑定作废
        speaker.team_code = None
        # 领取制（阶段十一）：旧属地任务已无法访问，清掉该发音人未录制的孤儿领取、
        # 把词条还给池子；已录制的领取保留（录音数据仍属该发音人，可审核/导出）。
        orphan_rows = (
            db.query(TaskClaim.id)
            .outerjoin(
                Recording,
                (Recording.task_id == TaskClaim.task_id)
                & (Recording.word_id == TaskClaim.word_id)
                & (Recording.speaker_id == TaskClaim.speaker_id),
            )
            .filter(TaskClaim.speaker_id == speaker.id, Recording.id.is_(None))
            .all()
        )
        if orphan_rows:
            db.query(TaskClaim).filter(
                TaskClaim.id.in_([r[0] for r in orphan_rows])
            ).delete()

    db.commit()
    db.refresh(speaker)
    return _to_out(speaker, _recording_counts(db), _review_counts(db))


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
    format: str = "csv",
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """导出发音人录音：csv=明细（全量，不受分页影响，遵循状态/任务筛选）；zip=明细+音频原文件打包。"""
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
    if format not in ("csv", "zip"):
        raise HTTPException(status_code=422, detail="format 仅支持 csv/zip")

    q = db.query(Recording).filter(Recording.speaker_id == speaker_id)
    if task_id is not None:
        q = q.filter(Recording.task_id == task_id)
    if status is not None:
        q = q.filter(Recording.status == status)
    recs = q.order_by(Recording.created_at.desc(), Recording.id.desc()).all()
    if format == "zip":
        if not recs:
            raise HTTPException(status_code=400, detail="该发音人暂无录音")

        def arcname(rec, out):
            province = speaker.province_code or "unknown"
            return f"audios/{province}/speaker_{speaker_id}/{Path(rec.audio_url).name}"

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return recordings_zip_response(
            db, recs, arcname, f"speaker_{speaker_id}_recordings_{ts}.zip"
        )

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


@router.delete("/{speaker_id}")
def delete_speaker(
    speaker_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """删除发音人（仅限无录音的发音人）。

    连带清理：领取记录（task_claims）、协议接受记录（speaker_agreements）、本地头像文件。
    省管理员只能删本省发音人（未绑定属地的也可删，与编辑语义一致）。
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
        raise HTTPException(status_code=403, detail="只能删除本省发音人")
    has_recording = (
        db.query(func.count())
        .select_from(Recording)
        .filter(Recording.speaker_id == speaker_id)
        .scalar()
        or 0
    )
    if has_recording:
        raise HTTPException(status_code=400, detail=f"该发音人已有 {has_recording} 条录音，不能删除")
    db.query(TaskClaim).filter(TaskClaim.speaker_id == speaker_id).delete()
    db.query(SpeakerAgreement).filter(SpeakerAgreement.speaker_id == speaker_id).delete()
    log_admin_action(
        db,
        admin,
        "删除发音人",
        "speaker",
        speaker.id,
        summary=f"删除发音人 #{speaker.id}「{speaker.nickname or speaker.device_id or '未命名'}」",
        ip=rate_limit.client_ip(request),
    )
    db.delete(speaker)
    db.commit()
    # commit 成功后清理本地头像文件（storage 只管录音，头像在 MEDIA_ROOT/avatars；失败不阻断）
    if speaker.avatar_url and speaker.avatar_url.startswith("/media/avatars/"):
        avatar_path = Path(settings.MEDIA_ROOT) / speaker.avatar_url.removeprefix("/media/")
        try:
            if avatar_path.is_file():
                avatar_path.unlink()
        except OSError:
            pass
    return {"detail": "已删除"}


@router.post("/merge")
def merge_speakers(
    body: SpeakerMergeRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """发音人合并：remove 的引用并入 keep 后删除 remove（同一人换设备产生的多身份合一）。

    引用迁移：Recording.speaker_id / TaskClaim.speaker_id / SpeakerAgreement.speaker_id。
    冲突处理：录音同 (task, word) 按状态保留策略去重（淘汰者连带删存储对象）；
    领取同 (task, word) keep 已领则删 remove 的；协议同 type 保留 version 大者。
    属地/团队码以 keep 为准；remove 的 device_id/openid 置空后再删（绕过唯一约束）并清头像。
    """
    keep = db.get(Speaker, body.keep_speaker_id)
    remove = db.get(Speaker, body.remove_speaker_id)
    if keep is None or remove is None:
        raise HTTPException(status_code=404, detail="发音人不存在")
    if keep.id == remove.id:
        raise HTTPException(status_code=400, detail="不能合并同一个发音人")
    for sp in (keep, remove):
        if (
            admin.role == "province_admin"
            and admin.province_code
            and sp.province_code
            and sp.province_code != admin.province_code
        ):
            raise HTTPException(status_code=403, detail="只能合并本省发音人")

    moved_rec = removed_rec = moved_claim = removed_claim = moved_agreement = removed_agreement = 0

    # —— Recording：迁移 speaker_id，同 (task, word) 冲突按状态保留策略去重 ——
    target_recs = {
        (r.task_id, r.word_id): r
        for r in db.query(Recording).filter(Recording.speaker_id == keep.id).all()
    }
    for r in db.query(Recording).filter(Recording.speaker_id == remove.id).all():
        key = (r.task_id, r.word_id)
        existing = target_recs.get(key)
        if existing is None:
            r.speaker_id = keep.id
            target_recs[key] = r
            moved_rec += 1
        else:
            better = _pick_better_recording(existing, r)
            loser = existing if better is r else r
            storage.delete_object(loser.audio_url)  # 淘汰者连带清理存储
            db.delete(loser)
            better.speaker_id = keep.id  # 胜者（无论原属哪方）统一归到 keep，避免孤儿引用
            target_recs[key] = better
            removed_rec += 1

    # —— TaskClaim：迁移，同 (task, word) keep 已领则删 remove 的 ——
    keep_claim_keys = {
        (cl.task_id, cl.word_id)
        for cl in db.query(TaskClaim).filter(TaskClaim.speaker_id == keep.id).all()
    }
    for cl in db.query(TaskClaim).filter(TaskClaim.speaker_id == remove.id).all():
        key = (cl.task_id, cl.word_id)
        if key in keep_claim_keys:
            db.delete(cl)
            removed_claim += 1
        else:
            cl.speaker_id = keep.id
            keep_claim_keys.add(key)
            moved_claim += 1

    # —— SpeakerAgreement：迁移，同 type 保留 version 大者 ——
    keep_agreements = {
        ag.type: ag
        for ag in db.query(SpeakerAgreement).filter(SpeakerAgreement.speaker_id == keep.id).all()
    }
    for ag in db.query(SpeakerAgreement).filter(SpeakerAgreement.speaker_id == remove.id).all():
        existing = keep_agreements.get(ag.type)
        if existing is None:
            ag.speaker_id = keep.id
            keep_agreements[ag.type] = ag
            moved_agreement += 1
        elif (ag.version or 0) > (existing.version or 0):
            # keep 已有同型但版本更低：原地升级 keep 的行并删 remove 的，
            # 避免「改挂 ag.speaker_id 再删 existing」撞 UNIQUE(speaker_id, type) 的暂态冲突。
            existing.version = ag.version
            existing.accepted_at = ag.accepted_at
            db.delete(ag)
            keep_agreements[ag.type] = existing
            removed_agreement += 1
        else:
            db.delete(ag)
            removed_agreement += 1

    # remove 的 device_id/openid 置空绕过唯一约束，删除 + 清头像文件（commit 后）
    remove.device_id = None
    remove.openid = None
    log_admin_action(
        db,
        admin,
        "合并发音人",
        "speaker",
        keep.id,
        summary=f"合并发音人 #{remove.id}「{remove.nickname or remove.device_id or ''}」→ #{keep.id}「{keep.nickname or keep.device_id or ''}」",
        detail={
            "moved_recordings": moved_rec,
            "removed_recordings": removed_rec,
            "moved_claims": moved_claim,
            "removed_claims": removed_claim,
            "moved_agreements": moved_agreement,
            "removed_agreements": removed_agreement,
        },
        ip=rate_limit.client_ip(request),
    )
    db.delete(remove)
    db.commit()
    if remove.avatar_url and remove.avatar_url.startswith("/media/avatars/"):
        avatar_path = Path(settings.MEDIA_ROOT) / remove.avatar_url.removeprefix("/media/")
        try:
            if avatar_path.is_file():
                avatar_path.unlink()
        except OSError:
            pass
    return {
        "detail": "已合并",
        "moved_recordings": moved_rec,
        "removed_recordings": removed_rec,
        "moved_claims": moved_claim,
        "removed_claims": removed_claim,
        "moved_agreements": moved_agreement,
        "removed_agreements": removed_agreement,
    }
