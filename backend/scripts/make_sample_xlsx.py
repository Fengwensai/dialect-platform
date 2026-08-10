"""生成 API 冒烟测试专用的最小样例词表（7 行，独立于正式词表）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import Workbook

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "test_sample.xlsx"

ROWS = [
    ("HB-001", "石家庄市长安区", "咋整", "这事咋整啊？", "核心词", "zǎ zhěng"),
    ("HB-002", "石家庄-桥西区", "晌午", "晌午吃啥？", "核心词", "shǎng wu"),
    ("HB-003", "保定市", "得劲儿", "这日子过得真得劲儿", "核心词", "děi jìnr"),
    ("HB-004", "邯郸市武安市", "夜个儿", "夜个儿下雨了", "核心词", "yè ger"),
    ("HB-005", "邢台市襄都区", "改天", "改天再去", "常用词", ""),
    ("HB-006", "张家口市", "麻利儿", "麻利儿点", "常用词", ""),
    ("HB-007", "找不到的方言点", "忒好", "这事儿忒好了", "测试无区划", ""),
]


def main():
    wb = Workbook()
    ws = wb.active
    ws.title = "河北省词表"
    ws.append(["编号", "方言点", "词条内容", "例句", "备注", "发音提示"])
    for r in ROWS:
        ws.append(list(r))
    wb.save(OUTPUT)
    print(f"[OK] 测试样例已生成：{OUTPUT}")


if __name__ == "__main__":
    main()
