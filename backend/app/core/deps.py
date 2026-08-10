from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.admin import AdminUser
from ..models.speaker import Speaker
from .security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def _decode(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        return decode_token(credentials.credentials)
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录"
        )


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AdminUser:
    payload = _decode(credentials)
    admin = db.get(AdminUser, payload.get("admin_id"))
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在")
    return admin


def get_current_speaker(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Speaker:
    """小程序发音人鉴权：token 必须带 speaker_id claim（区别于管理端的 admin_id）。"""
    payload = _decode(credentials)
    speaker = db.get(Speaker, payload.get("speaker_id"))
    if speaker is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="发音人不存在，请重新登录")
    return speaker


def get_current_speaker_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Speaker | None:
    """可选发音人鉴权：无/无效 token 返回 None（供上传接口在登录与 device_id 间兜底）。"""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
    except PyJWTError:
        return None
    return db.get(Speaker, payload.get("speaker_id"))


def require_super_admin(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if admin.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要超级管理员权限")
    return admin
