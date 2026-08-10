from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.deps import get_current_admin
from ..db import get_db
from ..models.admin import AdminUser
from ..models.region import Region

router = APIRouter(prefix="/api/regions", tags=["regions"])


@router.get("/tree")
def region_tree(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    regions = db.query(Region).order_by(Region.code).all()

    def children_of(parent_code: str, level: int) -> list[dict]:
        return [
            {
                "code": r.code,
                "name": r.name,
                "children": children_of(r.code, level + 1) if level < 3 else [],
            }
            for r in regions
            if r.parent_code == parent_code and r.level == level
        ]

    return [
        {
            "code": r.code,
            "name": r.name,
            "children": children_of(r.code, 2),
        }
        for r in regions
        if r.level == 1
    ]
