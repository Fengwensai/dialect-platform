from pydantic import BaseModel


class ExcelRow(BaseModel):
    row_index: int
    code: str = ""
    dialect_point: str = ""
    content: str = ""
    example_sentence: str = ""
    remark: str = ""
    pronunciation_hint: str = ""
    region_matched: bool = False


class UploadPreview(BaseModel):
    filename: str
    sheet_name: str
    headers: list[str]
    # 表头 -> 目标字段 的自动映射，前端可调整
    mapping: dict[str, str]
    total_rows: int
    rows: list[ExcelRow]
    # 每行原始单元格（与 rows 位置一一对应），供前端改映射后重建
    raw_rows: list[list[str]]


class ImportRequest(BaseModel):
    filename: str
    mapping: dict[str, str] = {}
    rows: list[ExcelRow]


class ImportResult(BaseModel):
    success_count: int
    fail_count: int
    errors: list[dict]
