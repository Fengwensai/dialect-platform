"""协议管理（阶段九）：三类协议版本管理。全部接口仅超管可访问。

编辑 = 生成新版本（version 递增，旧版本不可变），保存后所有发音人需重新同意。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.deps import require_super_admin
from ..db import get_db
from ..models.agreement import AGREEMENT_TYPES, Agreement
from ..schemas.agreement import AgreementCreate, AgreementOut

router = APIRouter(prefix="/api/agreements", tags=["agreements"])


def _validate_type(type_: str) -> None:
    if type_ not in AGREEMENT_TYPES:
        raise HTTPException(status_code=422, detail="type 不合法，须为 user_agreement / privacy_policy / voice_auth")


@router.get("", response_model=list[AgreementOut])
def list_latest_agreements(
    db: Session = Depends(get_db),
    admin=Depends(require_super_admin),
):
    """每类协议的最新版本（3 条）。"""
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


@router.get("/history", response_model=list[AgreementOut])
def agreement_history(
    type: str = Query(...),
    db: Session = Depends(get_db),
    admin=Depends(require_super_admin),
):
    """某类协议的全部版本（新→旧）。"""
    _validate_type(type)
    return (
        db.query(Agreement)
        .filter(Agreement.type == type)
        .order_by(Agreement.version.desc())
        .all()
    )


@router.post("", response_model=AgreementOut)
def create_agreement_version(
    body: AgreementCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_super_admin),
):
    """生成协议新版本：version = 该类 max+1（无则 1），旧版本保持不可变。"""
    _validate_type(body.type)
    title = body.title.strip()
    content = body.content.strip()
    if not title:
        raise HTTPException(status_code=422, detail="协议标题不能为空")
    if not content:
        raise HTTPException(status_code=422, detail="协议内容不能为空")

    max_version = (
        db.query(func.max(Agreement.version))
        .filter(Agreement.type == body.type)
        .scalar()
        or 0
    )
    ag = Agreement(
        type=body.type,
        title=title,
        content=content,
        version=max_version + 1,
        updated_by=admin.id,
    )
    db.add(ag)
    db.commit()
    db.refresh(ag)
    return ag
