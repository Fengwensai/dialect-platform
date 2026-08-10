from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.deps import get_current_admin
from ..core.security import create_access_token, verify_password
from ..db import get_db
from ..models.admin import AdminUser
from ..schemas.admin import AdminOut, LoginRequest, Token
from ..services import rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """管理后台登录。防爆破：连续失败超限按账号/按 IP 锁定，成功登录清零。"""
    ip = rate_limit.client_ip(request)
    acct_key = f"login:acct:{body.username}"
    ip_key = f"login:ip:{ip}"
    if rate_limit.blocked(acct_key, settings.LOGIN_FAIL_LIMIT, settings.LOGIN_FAIL_WINDOW_SECONDS) or \
            rate_limit.blocked(ip_key, settings.LOGIN_IP_FAIL_LIMIT, settings.LOGIN_FAIL_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")

    admin = db.query(AdminUser).filter(AdminUser.username == body.username).first()
    if admin is None or not verify_password(body.password, admin.password_hash):
        rate_limit.record_failure(acct_key, settings.LOGIN_FAIL_LIMIT, settings.LOGIN_FAIL_WINDOW_SECONDS)
        rate_limit.record_failure(ip_key, settings.LOGIN_IP_FAIL_LIMIT, settings.LOGIN_FAIL_WINDOW_SECONDS)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    rate_limit.reset(acct_key)
    rate_limit.reset(ip_key)
    token = create_access_token(
        {
            "admin_id": admin.id,
            "role": admin.role,
            "province_code": admin.province_code or "",
            "username": admin.username,
        }
    )
    return Token(access_token=token, admin=AdminOut.model_validate(admin))


@router.get("/me", response_model=AdminOut)
def me(admin: AdminUser = Depends(get_current_admin)):
    return admin
