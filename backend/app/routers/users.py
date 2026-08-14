from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..core.deps import require_super_admin
from ..core.security import hash_password
from ..db import get_db
from ..models.admin import AdminUser
from ..schemas.admin import AdminOut, UserCreate, UserUpdate
from ..services import rate_limit
from ..services.audit import log_admin_action

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[AdminOut])
def list_users(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_super_admin),
):
    users = db.query(AdminUser).order_by(AdminUser.id).all()
    return users


@router.post("", response_model=AdminOut)
def create_user(
    body: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_super_admin),
):
    if body.role not in ("super_admin", "province_admin"):
        raise HTTPException(status_code=400, detail="角色不合法")
    if body.role == "province_admin" and not body.province_code:
        raise HTTPException(status_code=400, detail="省管理员必须指定省份")
    exists = db.query(AdminUser).filter(AdminUser.username == body.username).first()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = AdminUser(
        username=body.username,
        password_hash=hash_password(body.password),
        name=body.name,
        role=body.role,
        province_code=body.province_code,
    )
    db.add(user)
    db.flush()
    log_admin_action(
        db,
        admin,
        "创建管理员",
        "admin",
        user.id,
        summary=f"新建管理员「{user.name or user.username}」（{user.role}）",
        ip=rate_limit.client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=AdminOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_super_admin),
):
    user = db.get(AdminUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="管理员不存在")

    data = body.model_dump(exclude_unset=True)
    changed = list(data.keys())
    password = data.pop("password", None)
    if password:
        user.password_hash = hash_password(password)
        changed.append("password")
    if data.get("role") == "province_admin" and not data.get("province_code"):
        raise HTTPException(status_code=400, detail="省管理员必须指定省份")
    for k, v in data.items():
        setattr(user, k, v)
    log_admin_action(
        db,
        admin,
        "修改管理员",
        "admin",
        user.id,
        summary=f"修改管理员「{user.name}」：{('、'.join(changed)) if changed else '无字段变化'}",
        detail=changed,
        ip=rate_limit.client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_super_admin),
):
    user = db.get(AdminUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="管理员不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    log_admin_action(
        db,
        admin,
        "删除管理员",
        "admin",
        user.id,
        summary=f"删除管理员「{user.name or user.username}」（{user.role}）",
        ip=rate_limit.client_ip(request),
    )
    db.delete(user)
    db.commit()
    return {"ok": True}
