"""驳回原因结构化（后台完善 2）。

审核驳回时从固定原因多选，落库 recordings.reject_reasons（key 逗号连接）。
本模块是原因清单唯一定义源；前端在视图内硬编码同款 key→label 映射（照 quality flags 先例）。
"""

REJECT_REASONS: list[tuple[str, str]] = [
    ("noise", "背景噪音"),
    ("misread", "念错"),
    ("too_quiet", "音量太小"),
    ("mandarin", "普通话混读"),
    ("incomplete", "不完整"),
    ("other", "其他"),
]

VALID_REJECT_REASONS: set[str] = {k for k, _ in REJECT_REASONS}
LABELS: dict[str, str] = dict(REJECT_REASONS)
