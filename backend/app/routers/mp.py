"""小程序端接口：录音上传（发音人端）。

本期过渡方案：不接微信登录，按 device_id（小程序本地生成的稳定 ID）识别发音人，
speakers.openid 预留用于后续 wx.login 换 openid。上传接口暂不要求 Bearer token。
"""
import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..core.agreements import (
    GUARD_DETAIL,
    pending_agreement_types,
    require_agreements_accepted,
)
from ..core.config import settings
from ..core.reject_reasons import LABELS as REJECT_LABELS
from ..core.deps import get_current_speaker, get_current_speaker_optional
from ..core.security import create_access_token
from ..db import get_db
from ..models.agreement import AGREEMENT_TYPES, Agreement, SpeakerAgreement
from ..models.recording import Recording
from ..models.region import Region
from ..models.speaker import Speaker
from ..models.task import TaskBatch, TaskBatchItem
from ..models.task_claim import TaskClaim
from ..models.team_code import TeamCode
from ..models.word import WordLibrary
from ..schemas.agreement import AgreementAcceptRequest, MpAcceptOut, MpAgreementOut
from ..schemas.mp import (
    LoginRequest,
    MpClaimOut,
    MpClaimRequest,
    MpClaimStats,
    MpDurationStats,
    MpOverallProgress,
    MpProgressOut,
    MpRegion,
    MpTaskOut,
    MpTaskSummary,
    MpToken,
    MpWordOut,
    ProfileUpdateRequest,
    RecordingOut,
    SpeakerOut,
    TeamJoinRequest,
)
from ..services import rate_limit, storage
from ..services.audio_quality import analyze_audio_quality, classify
from ..services.content_security import check_text, fire_media_check
from ..services.wechat import code_to_openid

router = APIRouter(prefix="/api/mp", tags=["mp"])

ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".aac"}
# 合规整改：头像不再上传服务器（隐私指引声明仅本地缓存），移除头像上传相关常量

GENDERS = {"male", "female", "other"}
AGE_BRACKETS = {"under18", "age18_30", "age31_45", "age46_60", "over60"}


def _validate_profile(gender: str | None, age_bracket: str | None) -> None:
    """画像取值校验：空串一律视为未提供（登录/上传不因此 422）；非法值 422。"""
    if gender is not None and gender != "" and gender not in GENDERS:
        raise HTTPException(status_code=422, detail="gender 仅支持 male/female/other")
    if age_bracket is not None and age_bracket != "" and age_bracket not in AGE_BRACKETS:
        raise HTTPException(
            status_code=422,
            detail="age_bracket 仅支持 under18/age18_30/age31_45/age46_60/over60",
        )


def _fill_profile_if_empty(
    speaker: Speaker, gender: str | None, age_bracket: str | None
) -> None:
    """空不覆盖：仅当新值非空且发音人当前为空时写入。"""
    if gender and not speaker.gender:
        speaker.gender = gender
    if age_bracket and not speaker.age_bracket:
        speaker.age_bracket = age_bracket


def _bound_or_400(speaker: Speaker) -> None:
    """属地门禁：未绑定团队（无省+市）禁止领取/上传。"""
    if not speaker.province_code or not speaker.city_code:
        raise HTTPException(status_code=400, detail="请先加入团队（输入团队码）后再操作")


def _region_matches(speaker: Speaker, task: TaskBatch) -> bool:
    """任务属地 == 发音人属地（同省同市；任务未限定区县则全城可见，限定了仅本区可见）。"""
    if not (speaker.province_code and speaker.city_code):
        return False
    if task.province_code != speaker.province_code:
        return False
    if task.city_code != speaker.city_code:
        return False
    if task.district_code and task.district_code != speaker.district_code:
        return False
    return True


def _speaker_upsert(
    db: Session,
    device_id: str | None,
    nickname: str | None,
    gender: str | None = None,
    age_bracket: str | None = None,
) -> Speaker:
    if not device_id:
        device_id = "anon_" + uuid4().hex[:12]
    speaker = db.query(Speaker).filter(Speaker.device_id == device_id).first()
    if speaker is None:
        speaker = Speaker(
            device_id=device_id,
            nickname=nickname or ("发音人" + device_id[-4:]),
            gender=gender or None,
            age_bracket=age_bracket or None,
        )
        db.add(speaker)
        db.flush()
    else:
        if nickname and nickname != speaker.nickname:
            speaker.nickname = nickname
        _fill_profile_if_empty(speaker, gender, age_bracket)
        db.flush()
    return speaker


def _ensure_task_accessible(task: TaskBatch | None, speaker: Speaker) -> TaskBatch:
    """领取/词条可见性守卫（阶段十一）：发布状态 + 演示/属地隔离，与 mp_task_words 一致。"""
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "published":
        raise HTTPException(status_code=400, detail="任务未发布")
    if task.is_demo:
        if speaker.province_code and speaker.city_code:
            raise HTTPException(status_code=403, detail="演示任务仅限未绑定团队的用户体验")
    else:
        _bound_or_400(speaker)
        if not _region_matches(speaker, task):
            raise HTTPException(status_code=403, detail="该任务不属于你所在地区")
    return task


def _claim_speaker(
    db: Session,
    current_speaker: Speaker | None,
    device_id: str | None,
) -> Speaker:
    """领取身份解析：token 优先，无 token 按 device_id 建档（与上传同一套，保证后续上传守卫命中）。"""
    if current_speaker is not None:
        return current_speaker
    return _speaker_upsert(db, device_id, None)


def _resolve_claim_actor(
    db: Session,
    current_speaker: Speaker | None,
    device_id: str | None,
) -> Speaker:
    """领取接口公共身份守卫：解析发音人 + 登录身份未同意最新协议则 403（匿名路径不拦，与上传一致）。"""
    speaker = _claim_speaker(db, current_speaker, device_id)
    if current_speaker is not None and pending_agreement_types(db, speaker.id):
        raise HTTPException(status_code=403, detail=GUARD_DETAIL)
    return speaker


def _task_pool(db: Session, task_id: int) -> tuple[int, list[int]]:
    """任务词条池：active 词条的去重 id（按 word_id 升序），返回 (count, ids)。"""
    rows = (
        db.query(TaskBatchItem.word_id)
        .join(WordLibrary, WordLibrary.id == TaskBatchItem.word_id)
        .filter(
            TaskBatchItem.task_batch_id == task_id,
            WordLibrary.status == "active",
        )
        .distinct()
        .order_by(TaskBatchItem.word_id)
        .all()
    )
    ids = [r[0] for r in rows]
    return len(ids), ids


def _claim_stats(db: Session, task: TaskBatch, speaker: Speaker) -> MpClaimStats:
    """当前发音人在某任务的领取统计（词条池视角）。"""
    pool, _ = _task_pool(db, task.id)
    claimed_ids = [
        r[0]
        for r in db.query(TaskClaim.word_id)
        .filter(TaskClaim.task_id == task.id)
        .all()
    ]
    my_ids = [
        r[0]
        for r in db.query(TaskClaim.word_id)
        .filter(TaskClaim.task_id == task.id, TaskClaim.speaker_id == speaker.id)
        .order_by(TaskClaim.word_id)
        .all()
    ]
    my_claimed = len(my_ids)
    available = max(0, pool - len(claimed_ids))
    cap = task.claim_limit if (task.claim_limit and task.claim_limit > 0) else pool
    claimable = max(0, min(cap - my_claimed, available))
    return MpClaimStats(
        task_word_total=pool,
        claim_limit=task.claim_limit,
        my_claimed=my_claimed,
        claimable=claimable,
        available=available,
        my_claim_word_ids=my_ids,
    )


@router.post("/recordings", response_model=RecordingOut)
async def upload_recording(
    background_tasks: BackgroundTasks,
    task_id: int = Form(...),
    word_id: int = Form(...),
    duration: int = Form(0),
    device_id: str | None = Form(None),
    nickname: str | None = Form(None),
    gender: str | None = Form(None),
    age_bracket: str | None = Form(None),
    file: UploadFile = File(...),
    current_speaker: Speaker | None = Depends(get_current_speaker_optional),
    db: Session = Depends(get_db),
):
    _validate_profile(gender, age_bracket)
    # 1. 任务校验：存在且已发布
    task = db.get(TaskBatch, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "published":
        raise HTTPException(status_code=400, detail="任务未发布")

    # 2. 词条归属校验：word 必须属于该任务
    belongs = (
        db.query(TaskBatchItem)
        .filter(
            TaskBatchItem.task_batch_id == task_id,
            TaskBatchItem.word_id == word_id,
        )
        .first()
    )
    if belongs is None:
        raise HTTPException(status_code=400, detail="词条不属于该任务")

    # 3. 文件校验
    filename = file.filename or ""
    ext = Path(filename).suffix.lower() or ".wav"
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="仅支持 .wav/.mp3/.m4a/.aac 音频")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="录音文件为空")
    max_size = settings.MAX_RECORDING_SIZE_MB * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"录音文件过大（限 {settings.MAX_RECORDING_SIZE_MB}MB）",
        )

    # 4. 发音人：优先登录身份（token），无 token 则按 device_id 建档（过渡方案）。
    #    登录态上传会绕过 _speaker_upsert，故对解析后的 speaker 无条件补画像（空不覆盖）。
    speaker = current_speaker or _speaker_upsert(
        db, device_id, nickname, gender, age_bracket
    )
    _fill_profile_if_empty(speaker, gender, age_bracket)

    # 4.4 质量预警拦截（后台完善 3）：管理员暂停该发音人上传，防低质录音灌入。
    #    放协议门禁之前：被暂停的发音人不消耗后续任何检查。
    if speaker.upload_paused:
        raise HTTPException(status_code=403, detail="该发音人已被暂停上传，请联系管理员")

    # 4.5 协议门禁（阶段九）：登录身份未同意最新版协议禁止上传；匿名 device_id 路径不拦。
    if current_speaker is not None and pending_agreement_types(db, current_speaker.id):
        raise HTTPException(status_code=403, detail=GUARD_DETAIL)

    # 5. 属地隔离（阶段八）：只能提交本团队绑定省市的已发布任务。
    #    演示任务（is_demo）：仅未绑定团队可上传；已绑定用户一律 403，演示数据隔离。
    if task.is_demo:
        if speaker.province_code and speaker.city_code:
            raise HTTPException(
                status_code=403, detail="演示任务仅限未绑定团队的用户上传"
            )
    else:
        _bound_or_400(speaker)
        if not _region_matches(speaker, task):
            raise HTTPException(status_code=403, detail="只能上传本团队所属地区的任务")

    # 5.6 领取制守卫（阶段十一）：只能上传「本人领取」的词条，否则词条不归该发音人专有。
    #     顺序必须在属地隔离之后（保 verify_demo_task 的 400/403 语义）、限流之前
    #     （未领取的 403 不消耗限流配额）。
    claim = (
        db.query(TaskClaim)
        .filter(
            TaskClaim.task_id == task_id,
            TaskClaim.word_id == word_id,
            TaskClaim.speaker_id == speaker.id,
        )
        .first()
    )
    if claim is None:
        raise HTTPException(
            status_code=403,
            detail="该词条未被你领取，请先在任务页领取",
        )

    # 5.5 上传频率限流（按发音人）：窗口内超限 429，客户端稍后重试（小程序有本地队列缓冲）。
    if not rate_limit.consume(
        f"upload:sp:{speaker.id}",
        settings.UPLOAD_RATE_LIMIT,
        settings.UPLOAD_RATE_WINDOW_SECONDS,
    ):
        raise HTTPException(
            status_code=429,
            detail=f"上传过于频繁，请稍后再试（{settings.UPLOAD_RATE_WINDOW_SECONDS // 60} 分钟内限 {settings.UPLOAD_RATE_LIMIT} 条）",
        )

    # 6. 覆盖策略：同 (task, word, speaker) 覆盖原行、保持 recording id 稳定
    existing = (
        db.query(Recording)
        .filter(
            Recording.task_id == task_id,
            Recording.word_id == word_id,
            Recording.speaker_id == speaker.id,
        )
        .first()
    )
    overwritten = existing is not None

    # 6.5 录音质量预检（纯标准库解析 WAV；非 WAV/解析失败记 unparsed，不影响上传）
    qc = analyze_audio_quality(content)
    if qc is None:
        q_status, q_flags, q_metrics = "unparsed", None, None
    else:
        q_status, q_flags = classify(qc)
        q_metrics = qc
    q_checked_at = datetime.now(timezone.utc)

    # 7. 落盘（key 确定：同一任务/词条/发音人重复上传即覆盖；COS/本地由 storage 统一收口）
    rel_key = f"recordings/{task_id}/{task_id}_{word_id}_{speaker.id}{ext}"
    audio_url = f"/media/{rel_key}"
    if existing and existing.audio_url != audio_url:
        # 扩展名变化（如 .wav→.mp3）旧 key 不同，删旧避免孤儿对象
        storage.delete_object(existing.audio_url)
    storage.put_object(audio_url, content)

    # 8. 入库（覆盖则更新原行，保持 recording id 稳定）
    if existing:
        existing.audio_url = audio_url
        existing.audio_duration = duration
        existing.file_size = len(content)
        existing.status = "pending"
        existing.review_note = None
        existing.reject_reasons = None  # 新音频覆盖旧驳回判决+原因
        existing.mandarin_transcript = None  # 新音频替换旧转写，需重填
        existing.dialect_transcript = None
        existing.quality_status = q_status
        existing.quality_flags = ",".join(q_flags) if q_flags else None
        existing.quality_metrics = q_metrics
        existing.quality_checked_at = q_checked_at
        rec = existing
    else:
        rec = Recording(
            task_id=task_id,
            word_id=word_id,
            speaker_id=speaker.id,
            audio_url=audio_url,
            audio_duration=duration,
            file_size=len(content),
            status="pending",
            quality_status=q_status,
            quality_flags=",".join(q_flags) if q_flags else None,
            quality_metrics=q_metrics,
            quality_checked_at=q_checked_at,
        )
        db.add(rec)
    db.commit()
    db.refresh(rec)

    # 内容安全（fail-open）：配置了 COS 或公网域名才发起音频异步检测；未配置/失败不影响响应。
    # media_url 由 fire_media_check 内生成（COS 预签名 / MEDIA_PUBLIC_BASE 拼接）。
    if storage.enabled() or settings.MEDIA_PUBLIC_BASE:
        background_tasks.add_task(fire_media_check, rec.id)

    return RecordingOut(
        recording_id=rec.id,
        audio_url=audio_url,
        status=rec.status,
        speaker_id=speaker.id,
        overwritten=overwritten,
    )


def _find_or_create_speaker(
    db: Session,
    openid: str,
    device_id: str | None,
    nickname: str | None,
    gender: str | None = None,
    age_bracket: str | None = None,
) -> Speaker:
    """登录身份解析：优先 openid，其次 device_id（与既有录音统一），否则新建。

    合规整改：头像不再上传服务器，登录不接收 avatar_url。
    属地（省+市）不再从登录/上传回填，唯一来源是团队码绑定（POST /api/mp/team/join）。
    """
    speaker = db.query(Speaker).filter(Speaker.openid == openid).first()
    if speaker is None and device_id:
        speaker = db.query(Speaker).filter(Speaker.device_id == device_id).first()
    if speaker is None:
        speaker = Speaker(
            openid=openid,
            device_id=device_id or None,
            nickname=nickname or ("发音人" + (device_id or openid)[-4:]),
            gender=gender or None,
            age_bracket=age_bracket or None,
        )
        db.add(speaker)
        db.flush()
        return speaker

    # 已存在：补绑身份，避免「登录一行 / device_id 上传一行」分叉
    if device_id and not speaker.device_id:
        dup = db.query(Speaker).filter(Speaker.device_id == device_id).first()
        if dup is None or dup.id == speaker.id:
            speaker.device_id = device_id
    if not speaker.openid:
        speaker.openid = openid
    # 回填画像（空则不覆盖已有值）
    if nickname and not speaker.nickname:
        speaker.nickname = nickname
    _fill_profile_if_empty(speaker, gender, age_bracket)
    return speaker


@router.post("/login", response_model=MpToken)
def mp_login(body: LoginRequest, db: Session = Depends(get_db)):
    """微信登录：code 换 openid，首次登录自动建档，返回发音人 token。"""
    _validate_profile(body.gender, body.age_bracket)
    if body.nickname is not None and body.nickname.strip():
        # 内容安全（fail-open）：命中 87014 才拒绝登录建档
        if check_text(body.nickname.strip()).blocked:
            raise HTTPException(status_code=400, detail="昵称包含违规内容")
    openid = code_to_openid(body.code)
    speaker = _find_or_create_speaker(
        db,
        openid,
        body.device_id,
        body.nickname,
        body.gender,
        body.age_bracket,
    )
    db.commit()
    db.refresh(speaker)

    token = create_access_token(
        {"speaker_id": speaker.id, "openid": speaker.openid or "", "role": "speaker"}
    )
    return MpToken(
        access_token=token,
        speaker=SpeakerOut.model_validate(speaker),
        pending_agreements=pending_agreement_types(db, speaker.id),
    )


@router.get("/agreements", response_model=list[MpAgreementOut])
def mp_agreements(db: Session = Depends(get_db)):
    """三类协议最新版本（公开，登录前即可阅读）。"""
    latest_ids = [
        db.query(Agreement.id)
        .filter(Agreement.type == t)
        .order_by(Agreement.version.desc())
        .limit(1)
        .scalar()
        for t in AGREEMENT_TYPES
    ]
    ids = [i for i in latest_ids if i is not None]
    if not ids:
        return []
    rows = db.query(Agreement).filter(Agreement.id.in_(ids)).all()
    by_type = {r.type: r for r in rows}
    return [by_type[t] for t in AGREEMENT_TYPES if t in by_type]


@router.post("/agreements/accept", response_model=MpAcceptOut)
def mp_accept_agreements(
    body: AgreementAcceptRequest,
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(get_current_speaker),
):
    """提交协议同意（Bearer）。整体校验通过才写库；陈旧版本 409 不写库。

    幂等：重复同意是 no-op；允许部分同意（未同意的下次再提交）。
    """
    if not body.accepted:
        raise HTTPException(status_code=422, detail="accepted 不能为空")
    # 1. 整体校验：type 合法 + (type, version) 是该 type 当前最新版本
    latest = dict(
        db.query(Agreement.type, func.max(Agreement.version)).group_by(Agreement.type).all()
    )
    for item in body.accepted:
        if item.type not in AGREEMENT_TYPES:
            raise HTTPException(status_code=422, detail=f"type 不合法：{item.type}")
        if latest.get(item.type) != item.version:
            raise HTTPException(
                status_code=409, detail="协议已更新，请重新阅读最新版本"
            )
    # 2. 写库：先删后插（幂等），仅覆盖本次提交的类型
    for item in body.accepted:
        db.query(SpeakerAgreement).filter(
            SpeakerAgreement.speaker_id == speaker.id,
            SpeakerAgreement.type == item.type,
        ).delete(synchronize_session=False)
        db.add(
            SpeakerAgreement(
                speaker_id=speaker.id,
                type=item.type,
                version=item.version,
            )
        )
    db.commit()
    return MpAcceptOut(pending_agreements=pending_agreement_types(db, speaker.id))


@router.get("/agreements/pending", response_model=MpAcceptOut)
def mp_pending_agreements(
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(get_current_speaker),
):
    """我尚未同意最新版的协议 type（冷启动/版本升级后由登录页轮询判定）。"""
    return MpAcceptOut(pending_agreements=pending_agreement_types(db, speaker.id))


@router.post("/profile", response_model=SpeakerOut)
def update_my_profile(
    body: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(require_agreements_accepted),
):
    """发音人自助更新资料：明确意图直接覆盖；空串清空；null 不改（nickname 非空才改，昵称不可为空）。"""
    _validate_profile(body.gender, body.age_bracket)
    if body.gender is not None:
        speaker.gender = body.gender or None
    if body.age_bracket is not None:
        speaker.age_bracket = body.age_bracket or None
    if body.nickname is not None and body.nickname.strip():
        # 内容安全（fail-open）：微信不可达/非违规时放行，命中 87014 才拒绝
        if check_text(body.nickname.strip()).blocked:
            raise HTTPException(status_code=400, detail="昵称包含违规内容")
        speaker.nickname = body.nickname.strip()
    # 头像不再存储于服务器（合规整改：隐私指引声明仅本地缓存），不在此更新
    # 属地（省/市）锁定：由团队码绑定决定，此处不改
    db.commit()
    db.refresh(speaker)
    return SpeakerOut.model_validate(speaker)


@router.post("/team/join", response_model=SpeakerOut)
def team_join(
    body: TeamJoinRequest,
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(require_agreements_accepted),
):
    """加入团队：凭团队码绑定属地（省+市+区县），绑定后锁定不可自改。

    一码一区县（后台建码时保证），同地区发音人绑到同一属地，天然隔离——
    只能看到/录制本区县（及本市未限定区县）任务。
    """
    if speaker.team_code:
        raise HTTPException(
            status_code=400,
            detail=f"已绑定团队（{speaker.team_code}），无法更换；如需修改请联系管理员",
        )
    code = (body.code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail="团队码不能为空")
    tc = db.query(TeamCode).filter(TeamCode.code == code).first()
    if tc is None:
        raise HTTPException(status_code=404, detail="团队码不存在或已停用")
    speaker.province_code = tc.province_code
    speaker.city_code = tc.city_code
    speaker.district_code = tc.district_code
    speaker.team_code = tc.code
    db.commit()
    db.refresh(speaker)
    return SpeakerOut.model_validate(speaker)


@router.get("/tasks")
def mp_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(require_agreements_accepted),
):
    """我的可用任务：强制按发音人属地（省+市+区县）返回已发布任务，附词条数与我的已录进度。

    阶段八隔离：服务端按 speaker 绑定属地过滤，忽略任何客户端区域参数；
    未绑定团队返回空列表。
    演示任务（is_demo，审核/体验用）：未绑定团队只返回演示任务；已绑定只返回本地区非演示任务。
    """
    unbound = not (speaker.province_code and speaker.city_code)
    q = db.query(TaskBatch).filter(TaskBatch.status == "published")
    if unbound:
        q = q.filter(TaskBatch.is_demo.is_(True))
    else:
        q = q.filter(
            TaskBatch.is_demo.is_(False),
            TaskBatch.province_code == speaker.province_code,
            TaskBatch.city_code == speaker.city_code,
            or_(
                TaskBatch.district_code.is_(None),
                TaskBatch.district_code == speaker.district_code,
            ),
        )
    total = q.count()
    batches = (
        q.order_by(TaskBatch.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    if batches:
        ids = [b.id for b in batches]
        word_counts = dict(
            db.query(TaskBatchItem.task_batch_id, func.count(TaskBatchItem.id))
            .filter(TaskBatchItem.task_batch_id.in_(ids))
            .group_by(TaskBatchItem.task_batch_id)
            .all()
        )
        rec_counts = dict(
            db.query(Recording.task_id, func.count(func.distinct(Recording.word_id)))
            .filter(
                Recording.task_id.in_(ids),
                Recording.speaker_id == speaker.id,
            )
            .group_by(Recording.task_id)
            .all()
        )
        rej_counts = dict(
            db.query(Recording.task_id, func.count(func.distinct(Recording.word_id)))
            .filter(
                Recording.task_id.in_(ids),
                Recording.speaker_id == speaker.id,
                Recording.status == "rejected",
            )
            .group_by(Recording.task_id)
            .all()
        )
        # 领取制（阶段十一）：词条池（active 去重）、全任务已领、我当前已领
        pool_counts = dict(
            db.query(
                TaskBatchItem.task_batch_id,
                func.count(func.distinct(WordLibrary.id)),
            )
            .join(WordLibrary, WordLibrary.id == TaskBatchItem.word_id)
            .filter(
                TaskBatchItem.task_batch_id.in_(ids),
                WordLibrary.status == "active",
            )
            .group_by(TaskBatchItem.task_batch_id)
            .all()
        )
        claimed_counts = dict(
            db.query(TaskClaim.task_id, func.count(TaskClaim.id))
            .filter(TaskClaim.task_id.in_(ids))
            .group_by(TaskClaim.task_id)
            .all()
        )
        my_claim_counts = dict(
            db.query(TaskClaim.task_id, func.count(TaskClaim.id))
            .filter(
                TaskClaim.task_id.in_(ids),
                TaskClaim.speaker_id == speaker.id,
            )
            .group_by(TaskClaim.task_id)
            .all()
        )
    else:
        word_counts, rec_counts, rej_counts = {}, {}, {}
        pool_counts, claimed_counts, my_claim_counts = {}, {}, {}

    items = []
    for b in batches:
        out = MpTaskOut.model_validate(b)
        out.word_count = word_counts.get(b.id, 0)
        out.recorded_count = rec_counts.get(b.id, 0)
        out.rejected_count = rej_counts.get(b.id, 0)
        pool = pool_counts.get(b.id, 0)
        my_claimed = my_claim_counts.get(b.id, 0)
        available = max(0, pool - claimed_counts.get(b.id, 0))
        cap = b.claim_limit if (b.claim_limit and b.claim_limit > 0) else pool
        out.claim_limit = b.claim_limit
        out.my_claimed = my_claimed
        out.available = available
        out.claimable = max(0, min(cap - my_claimed, available))
        items.append(out)
    return {"total": total, "items": items}


@router.get("/tasks/{task_id}/words")
def mp_task_words(
    task_id: int,
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(require_agreements_accepted),
):
    """任务词条列表（领取制，阶段十一）：只返回**当前发音人已领取**的词条，附已录状态。

    未领取前返回空列表 + 领取统计（claim），前端据此引导「先去领取」。
    阶段八隔离：非本地区任务直接 403，防止通过任务 ID 越权查看/录制。
    """
    task = db.get(TaskBatch, task_id)
    _ensure_task_accessible(task, speaker)

    my_claim_ids = [
        r[0]
        for r in db.query(TaskClaim.word_id)
        .filter(TaskClaim.task_id == task_id, TaskClaim.speaker_id == speaker.id)
        .all()
    ]
    my_claim_set = set(my_claim_ids)

    items_q = (
        db.query(TaskBatchItem)
        .filter(TaskBatchItem.task_batch_id == task_id)
        .all()
    )
    word_ids = [it.word_id for it in items_q]
    words = (
        db.query(WordLibrary)
        .filter(WordLibrary.id.in_(word_ids), WordLibrary.status == "active")
        .all()
        if word_ids
        else []
    )
    word_map = {w.id: w for w in words}

    recs = (
        db.query(Recording)
        .filter(
            Recording.task_id == task_id,
            Recording.speaker_id == speaker.id,
        )
        .all()
    )
    rec_map = {r.word_id: r for r in recs}  # 同 (task,word,speaker) 覆盖后仅一条

    out_items = []
    for it in items_q:
        w = word_map.get(it.word_id)
        if w is None or it.word_id not in my_claim_set:
            continue
        r = rec_map.get(it.word_id)
        # 驳回原因/备注：仅 rejected 时返回（label 由 key 逗号串映射成人类可读；备注为自由文本，
        # 通过/待审时一律不透出，避免把审核备注泄给发音人）
        reject_reasons = None
        review_note = None
        if r is not None and r.status == "rejected":
            if r.reject_reasons:
                reject_reasons = [
                    REJECT_LABELS[k] for k in r.reject_reasons.split(",") if k in REJECT_LABELS
                ]
            review_note = r.review_note or None
        out_items.append(
            MpWordOut(
                word_id=w.id,
                code=w.code,
                content=w.content,
                example_sentence=w.example_sentence,
                pronunciation_hint=w.pronunciation_hint,
                remark=w.remark,
                mandarin_transcript=r.mandarin_transcript if r else None,
                dialect_transcript=r.dialect_transcript if r else None,
                recorded=r is not None,
                recording_id=r.id if r else None,
                status=r.status if r else None,
                reject_reasons=reject_reasons,
                review_note=review_note,
            )
        )
    return {
        "task": MpTaskSummary.model_validate(task),
        "total": len(out_items),
        "items": out_items,
        "claim": _claim_stats(db, task, speaker),
    }


@router.get("/tasks/{task_id}/claims", response_model=MpClaimStats)
def my_claims(
    task_id: int,
    device_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_speaker: Speaker | None = Depends(get_current_speaker_optional),
):
    """我的领取统计（领取制）：任务词条池视角。"""
    speaker = _resolve_claim_actor(db, current_speaker, device_id)
    task = db.get(TaskBatch, task_id)
    _ensure_task_accessible(task, speaker)
    return _claim_stats(db, task, speaker)


@router.post("/tasks/{task_id}/claims", response_model=MpClaimOut)
def claim_words(
    task_id: int,
    body: MpClaimRequest,
    db: Session = Depends(get_db),
    current_speaker: Speaker | None = Depends(get_current_speaker_optional),
):
    """领取词条（领取制）：count 模式自动按 word_id 取前 N 条；word_ids 模式精确领取。

    原子性：事务内 SELECT ... FOR UPDATE 锁任务行，串行化同任务并发领取；
    锁内预计算可领数，插完即 commit，无需重试。
    """
    if (body.count is None) == (body.word_ids is None):
        raise HTTPException(status_code=422, detail="count 与 word_ids 二选一且必填")
    requested = len(body.word_ids) if body.word_ids is not None else (body.count or 0)
    if requested <= 0:
        raise HTTPException(status_code=422, detail="领取条数必须 ≥ 1")

    speaker = _resolve_claim_actor(db, current_speaker, body.device_id)
    task = (
        db.query(TaskBatch)
        .filter(TaskBatch.id == task_id)
        .with_for_update()
        .first()
    )
    _ensure_task_accessible(task, speaker)

    _, pool_ids = _task_pool(db, task_id)
    claimed_ids = [
        r[0]
        for r in db.query(TaskClaim.word_id)
        .filter(TaskClaim.task_id == task_id)
        .all()
    ]
    claimed_set = set(claimed_ids)
    my_claimed = (
        db.query(func.count(TaskClaim.id))
        .filter(TaskClaim.task_id == task_id, TaskClaim.speaker_id == speaker.id)
        .scalar()
    )
    available = max(0, len(pool_ids) - len(claimed_ids))
    cap = (
        task.claim_limit
        if (task.claim_limit and task.claim_limit > 0)
        else len(pool_ids)
    )
    claimable = max(0, min(cap - my_claimed, available))

    if body.word_ids is not None:
        if len(body.word_ids) != len(set(body.word_ids)):
            raise HTTPException(status_code=422, detail="word_ids 存在重复")
        pool_set = set(pool_ids)
        bad = [w for w in body.word_ids if w not in pool_set]
        taken = [w for w in body.word_ids if w in claimed_set]
        if bad or taken or len(body.word_ids) > claimable:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="部分词条不可领取（已领/不属于本任务/超上限），请刷新后重试",
            )
        new_ids = body.word_ids
    else:
        take = min(requested, claimable)
        new_ids = [w for w in pool_ids if w not in claimed_set][:take]
        if len(new_ids) == 0:
            db.rollback()
            raise HTTPException(status_code=409, detail="当前无可领取词条或已达领取上限")

    for wid in new_ids:
        db.add(TaskClaim(task_id=task_id, word_id=wid, speaker_id=speaker.id))
    db.commit()
    return MpClaimOut(claimed_word_ids=new_ids, stats=_claim_stats(db, task, speaker))


@router.delete("/tasks/{task_id}/claims/{word_id}", response_model=MpClaimStats)
def release_claim(
    task_id: int,
    word_id: int,
    device_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_speaker: Speaker | None = Depends(get_current_speaker_optional),
):
    """自退已领取但未录制的词条（退回后别人可领）；已录制 400。"""
    speaker = _resolve_claim_actor(db, current_speaker, device_id)
    task = db.get(TaskBatch, task_id)
    _ensure_task_accessible(task, speaker)
    claim = (
        db.query(TaskClaim)
        .filter(
            TaskClaim.task_id == task_id,
            TaskClaim.word_id == word_id,
            TaskClaim.speaker_id == speaker.id,
        )
        .with_for_update()
        .first()
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="该词条未被你领取")
    rec = (
        db.query(Recording)
        .filter(
            Recording.task_id == task_id,
            Recording.word_id == word_id,
            Recording.speaker_id == speaker.id,
        )
        .first()
    )
    if rec is not None:
        raise HTTPException(status_code=400, detail="已录制不能退回")
    db.delete(claim)
    db.commit()
    return _claim_stats(db, task, speaker)


@router.get("/recordings/progress", response_model=MpProgressOut)
def mp_progress(
    task_id: int,
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(require_agreements_accepted),
):
    """我的录音进度：按状态统计当前发音人在该任务的录音。"""
    task = db.get(TaskBatch, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _bound_or_400(speaker)
    if not _region_matches(speaker, task):
        raise HTTPException(status_code=403, detail="该任务不属于你所在地区")
    total = (
        db.query(func.count())
        .select_from(TaskBatchItem)
        .filter(TaskBatchItem.task_batch_id == task_id)
        .scalar()
        or 0
    )
    rows = (
        db.query(Recording.status, func.count())
        .filter(
            Recording.task_id == task_id,
            Recording.speaker_id == speaker.id,
        )
        .group_by(Recording.status)
        .all()
    )
    counts = {s: c for s, c in rows}
    pending = counts.get("pending", 0)
    approved = counts.get("approved", 0)
    rejected = counts.get("rejected", 0)
    return MpProgressOut(
        task_id=task_id,
        total_words=total,
        recorded=pending + approved + rejected,
        pending=pending,
        approved=approved,
        rejected=rejected,
    )


@router.get("/progress", response_model=MpOverallProgress)
def mp_overall_progress(
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(require_agreements_accepted),
):
    """我的总体录音进度：跨任务按状态汇总（首页展示）。"""
    rows = (
        db.query(Recording.status, func.count())
        .filter(Recording.speaker_id == speaker.id)
        .group_by(Recording.status)
        .all()
    )
    counts = {s: c for s, c in rows}
    pending = counts.get("pending", 0)
    approved = counts.get("approved", 0)
    rejected = counts.get("rejected", 0)
    return MpOverallProgress(
        recorded=pending + approved + rejected,
        pending=pending,
        approved=approved,
        rejected=rejected,
    )


@router.get("/regions", response_model=list[MpRegion])
def mp_regions(
    parent_code: str | None = None,
    db: Session = Depends(get_db),
):
    """区划列表（公开）：不传 parent_code 返回省（level 1）；传省级代码返回其市。

    阶段八：小程序用省+市两级解析发音人属地名（团队码绑定后展示用）。
    """
    if parent_code:
        parent = db.get(Region, parent_code)
        if parent is None:
            raise HTTPException(status_code=404, detail="上级区划不存在")
        return (
            db.query(Region)
            .filter(Region.parent_code == parent_code, Region.level == parent.level + 1)
            .order_by(Region.code)
            .all()
        )
    return db.query(Region).filter(Region.level == 1).order_by(Region.code).all()


REC_STATUS_LABELS = {"pending": "待审核", "approved": "已通过", "rejected": "已驳回"}


def _csv_response(rows: list[dict], columns: list[str], fname: str) -> Response:
    """utf-8-sig CSV 下载响应（Excel 双击可直接打开中文）。

    plain `filename` 用 ASCII 兜底（Starlette 以 latin-1 编码 header，中文文件名会炸），
    中文名走 RFC 5987 `filename*=UTF-8''…`。
    """
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=text.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="durations_export.csv"; filename*=UTF-8\'\'{quote(fname)}'
        },
    )


@router.get("/me/durations", response_model=MpDurationStats)
def my_duration_stats(
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(require_agreements_accepted),
):
    """我的录音时长统计（全部任务，按状态汇总，时长毫秒）。"""
    rows = (
        db.query(
            Recording.status,
            func.count(),
            func.coalesce(func.sum(Recording.audio_duration), 0),
        )
        .filter(Recording.speaker_id == speaker.id)
        .group_by(Recording.status)
        .all()
    )
    stats = {st: {"cnt": c, "dur": d} for st, c, d in rows}

    def pick(st: str) -> dict:
        return stats.get(st, {"cnt": 0, "dur": 0})

    pending = pick("pending")
    approved = pick("approved")
    rejected = pick("rejected")
    total_cnt = pending["cnt"] + approved["cnt"] + rejected["cnt"]
    total_dur = pending["dur"] + approved["dur"] + rejected["dur"]
    return MpDurationStats(
        total_count=total_cnt,
        total_duration_ms=total_dur,
        pending_count=pending["cnt"],
        pending_duration_ms=pending["dur"],
        approved_count=approved["cnt"],
        approved_duration_ms=approved["dur"],
        rejected_count=rejected["cnt"],
        rejected_duration_ms=rejected["dur"],
    )


@router.get("/me/export")
def my_duration_export(
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(require_agreements_accepted),
):
    """导出我的录音时长明细 CSV（utf-8-sig，Excel 可直接打开）。"""
    recs = (
        db.query(Recording)
        .filter(Recording.speaker_id == speaker.id)
        .order_by(Recording.created_at.desc(), Recording.id.desc())
        .all()
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
        task = db.get(TaskBatch, r.task_id)
        word = db.get(WordLibrary, r.word_id)
        rows.append(
            {
                "录音ID": r.id,
                "任务": task.name if task else f"任务#{r.task_id}",
                "词条编码": word.code if word else "",
                "词条内容": word.content if word else f"词条#{r.word_id}",
                "状态": REC_STATUS_LABELS.get(r.status, r.status),
                "时长_ms": r.audio_duration,
                "文件大小_B": r.file_size,
                "审核备注": r.review_note or "",
                "审核时间": r.reviewed_at.isoformat() if r.reviewed_at else "",
                "提交时间": r.created_at.isoformat() if r.created_at else "",
                "音频路径": r.audio_url,
            }
        )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return _csv_response(rows, columns, f"我的录音时长_{ts}.csv")
