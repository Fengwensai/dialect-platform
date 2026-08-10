from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..core.deps import get_current_admin
from ..db import get_db
from ..models.admin import AdminUser
from ..models.import_log import ExcelImportLog
from ..models.word import WordLibrary
from ..schemas.excel import ExcelRow, ImportRequest, ImportResult, UploadPreview
from ..services import excel_parser
from ..services.region_matcher import match_region, province_from_filename

router = APIRouter(prefix="/api/excel", tags=["excel"])


@router.post("/upload", response_model=UploadPreview)
def upload_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx/.xlsm 格式")
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件内容为空")
    sheet_name, headers, mapping, parsed_rows, raw_cells = excel_parser.parse_workbook(
        data, file.filename
    )
    default_province = province_from_filename(db, file.filename)

    rows: list[ExcelRow] = []
    for item in parsed_rows:
        region = match_region(db, item.get("dialect_point"), default_province)
        rows.append(
            ExcelRow(
                row_index=item.get("_row", 0),
                code=item.get("code", ""),
                dialect_point=item.get("dialect_point", ""),
                content=item.get("content", ""),
                example_sentence=item.get("example_sentence", ""),
                remark=item.get("remark", ""),
                pronunciation_hint=item.get("pronunciation_hint", ""),
                region_matched=bool(region.get("city_code") or region.get("district_code")),
            )
        )

    return UploadPreview(
        filename=file.filename,
        sheet_name=sheet_name,
        headers=headers,
        mapping=mapping,
        total_rows=len(rows),
        rows=rows,
        raw_rows=raw_cells,
    )


@router.post("/import", response_model=ImportResult)
def import_excel(
    body: ImportRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    errors: list[dict] = []
    success = 0
    default_province = province_from_filename(db, body.filename)

    for r in body.rows:
        if not r.content:
            continue
        region = match_region(db, r.dialect_point, default_province)

        # 省管理员只能导入自己省份的词条
        if admin.role == "province_admin":
            if region["province_code"] != admin.province_code:
                errors.append(
                    {
                        "row": r.row_index,
                        "content": r.content,
                        "reason": "区划不属于本管理员管辖范围或无法匹配",
                    }
                )
                continue

        db.add(
            WordLibrary(
                code=r.code[:64],
                dialect_point=r.dialect_point[:128],
                content=r.content[:255],
                example_sentence=r.example_sentence[:500] or None,
                remark=r.remark[:500] or None,
                pronunciation_hint=r.pronunciation_hint[:500] or None,
                province_code=region["province_code"],
                city_code=region["city_code"],
                district_code=region["district_code"],
                created_by=admin.id,
            )
        )
        success += 1

    db.commit()
    db.add(
        ExcelImportLog(
            filename=body.filename[:255],
            total_rows=len(body.rows),
            success_count=success,
            fail_count=len(errors),
            errors=errors,
            admin_id=admin.id,
        )
    )
    db.commit()
    return ImportResult(success_count=success, fail_count=len(errors), errors=errors)
