from pydantic import BaseModel


class OrphanItem(BaseModel):
    """一条孤儿引用明细：子行 id + 悬空引用值 + 中文说明。"""

    id: int
    ref: str
    detail: str


class OrphanCategory(BaseModel):
    """一类孤儿引用：count 为全量计数，items 为明细（可能截断，见服务层 MAX_ITEMS）。"""

    key: str
    name: str
    count: int
    items: list[OrphanItem]


class DataHealthReport(BaseModel):
    """孤儿引用巡检报告（9 类核心业务引用）。"""

    total: int
    categories: list[OrphanCategory]


class RepairRequest(BaseModel):
    """一键修复请求：category 为 None 修全部；ids 限定该类中指定子行（均 None 修全量）。"""

    category: str | None = None
    ids: list[int] | None = None


class RepairResult(BaseModel):
    """修复结果：deleted 为各分类删除数，total 为总删除数。"""

    deleted: dict[str, int]
    total: int
