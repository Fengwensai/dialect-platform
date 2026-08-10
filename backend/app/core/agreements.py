"""协议守卫（阶段九）：发音人须同意三类协议的最新版本方可使用功能接口。

设计：登录仍发 token（否则无法调同意接口），但未全部同意前所有功能接口 403。
守卫是 fail-open 的——若 agreements 表为空（迁移未跑）则 nothing pending，不锁死所有人。
"""
from fastapi import Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.agreement import Agreement, SpeakerAgreement
from ..models.speaker import Speaker
from .deps import get_current_speaker

GUARD_DETAIL = "请先同意最新版用户协议、隐私政策与声音授权协议"


def pending_agreement_types(db: Session, speaker_id: int) -> list[str]:
    """返回该发音人尚未同意最新版的三类协议 type 列表（空 = 全部已同意）。"""
    latest = dict(
        db.query(Agreement.type, func.max(Agreement.version)).group_by(Agreement.type).all()
    )
    accepted = dict(
        db.query(SpeakerAgreement.type, SpeakerAgreement.version)
        .filter(SpeakerAgreement.speaker_id == speaker_id)
        .all()
    )
    return [t for t, v in latest.items() if accepted.get(t, -1) < v]


def require_agreements_accepted(
    db: Session = Depends(get_db),
    speaker: Speaker = Depends(get_current_speaker),
) -> Speaker:
    """功能接口守卫：未全部同意最新版协议 → 403。返回 Speaker，可直接替换 get_current_speaker。"""
    if pending_agreement_types(db, speaker.id):
        raise HTTPException(status_code=403, detail=GUARD_DETAIL)
    return speaker
