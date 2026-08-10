"""团队码管理（阶段八）：一码一区（省+市），发音人凭码绑定属地。

超管管理全国团队码；省管理员仅能管理本省团队码。改区域/改码会让已绑定发音人
失联，故只允许改名，区域变更需删除后重建。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.deps import get_current_admin
from ..db import get_db
from ..models.admin import AdminUser
from ..models.region import Region
from ..models.team_code import TeamCode
from ..schemas.team import TeamCodeCreate, TeamCodeOut, TeamCodeUpdate

router = APIRouter(prefix="/api/team-codes", tags=["team-codes"])


def _normalize(code: str) -> str:
    return (code or "").strip().upper()


def _assert_region_scope(admin: AdminUser, province_code: str) -> None:
    """省管理员只能在本省范围内建/改/删团队码。"""
    if (
        admin.role == "province_admin"
        and admin.province_code
        and province_code != admin.province_code
    ):
        raise HTTPException(status_code=403, detail="省管理员只能管理本省的团队码")


def _validate_region(db: Session, province_code: str, city_code: str) -> None:
    """校验省+市是有效的一级/二级区划，且市归属该省。"""
    province = db.get(Region, province_code)
    if province is None or province.level != 1:
        raise HTTPException(status_code=422, detail="province_code 无效，须为有效省级代码")
    city = db.get(Region, city_code)
    if city is None or city.level != 2 or city.parent_code != province_code:
        raise HTTPException(status_code=422, detail="city_code 无效，须为归属该省的市级代码")


@router.get("", response_model=list[TeamCodeOut])
def list_team_codes(
    province_code: str | None = None,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """团队码列表。省管理员强制限本省；超管可按 province_code 筛选。"""
    q = db.query(TeamCode)
    if admin.role == "province_admin" and admin.province_code:
        q = q.filter(TeamCode.province_code == admin.province_code)
    elif province_code:
        q = q.filter(TeamCode.province_code == province_code)
    return q.order_by(TeamCode.id).all()


@router.post("", response_model=TeamCodeOut)
def create_team_code(
    body: TeamCodeCreate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """创建团队码：code 唯一、一码一区（省+市唯一）。"""
    code = _normalize(body.code)
    if not code:
        raise HTTPException(status_code=422, detail="团队码不能为空")
    _assert_region_scope(admin, body.province_code)
    _validate_region(db, body.province_code, body.city_code)
    if db.query(TeamCode).filter(TeamCode.code == code).first():
        raise HTTPException(status_code=400, detail="团队码已存在")
    exists = (
        db.query(TeamCode)
        .filter(
            TeamCode.province_code == body.province_code,
            TeamCode.city_code == body.city_code,
        )
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=400,
            detail="该省市已有团队码（一码一区），如需更换请删除后重建",
        )

    tc = TeamCode(
        code=code,
        name=body.name.strip() or code,
        province_code=body.province_code,
        city_code=body.city_code,
        created_by=admin.id,
    )
    db.add(tc)
    db.commit()
    db.refresh(tc)
    return tc


@router.patch("/{team_id}", response_model=TeamCodeOut)
def update_team_code(
    team_id: int,
    body: TeamCodeUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """仅可改团队名。"""
    tc = db.get(TeamCode, team_id)
    if tc is None:
        raise HTTPException(status_code=404, detail="团队码不存在")
    _assert_region_scope(admin, tc.province_code)
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="团队名不能为空")
        tc.name = name
    db.commit()
    db.refresh(tc)
    return tc


@router.delete("/{team_id}")
def delete_team_code(
    team_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """删除团队码。已绑定发音人属地保留（不受影响），但不再接受该码新绑定。"""
    tc = db.get(TeamCode, team_id)
    if tc is None:
        raise HTTPException(status_code=404, detail="团队码不存在")
    _assert_region_scope(admin, tc.province_code)
    db.delete(tc)
    db.commit()
    return {"ok": True}
