"""后端 API 全流程冒烟测试：登录 → 上传解析 → 导入 → 词条查询 → 任务创建/发布 → 省管理员隔离。"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000"
SAMPLE = Path(__file__).resolve().parent.parent / "data" / "test_sample.xlsx"

passed = 0
failed = 0


def cleanup():
    """清空业务表，保证测试可重复运行。"""
    from app.db import SessionLocal
    from app.models.import_log import ExcelImportLog
    from app.models.task import TaskBatch, TaskBatchItem
    from app.models.word import WordLibrary

    db = SessionLocal()
    try:
        db.query(TaskBatchItem).delete()
        db.query(TaskBatch).delete()
        db.query(WordLibrary).delete()
        db.query(ExcelImportLog).delete()
        db.commit()
        print("[cleanup] 业务表已清空")
    finally:
        db.close()


cleanup()


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {extra}")


def login(username, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()["access_token"]


print("== 1. 登录 ==")
admin_token = login("admin", "admin123")
hebei_token = login("hebei_admin", "admin123")
check("admin 登录", bool(admin_token))
check("hebei_admin 登录", bool(hebei_token))

print("== 2. Excel 上传解析预览 ==")
with open(SAMPLE, "rb") as f:
    r = requests.post(
        f"{BASE}/api/excel/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("河北省词表.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
print(f"  status={r.status_code}")
if r.status_code != 200:
    print("  resp:", r.text[:500])
else:
    pv = r.json()
    check("表头自动映射含 content", "content" in pv["mapping"].values())
    check("预览行数", pv["total_rows"] == 7, f"got {pv['total_rows']}")
    matched = [row for row in pv["rows"] if row["region_matched"]]
    check("6 条解析出市/区县", len(matched) == 6, f"matched={len(matched)}")
    check("HB-007 仅文件名兜底省、无市/区县被标记", any(r["content"] == "忒好" and not r["region_matched"] for r in pv["rows"]))
    # 展示每行的匹配情况
    for row in pv["rows"]:
        print(f"    {row['row_index']}: {row['content']} <{row['dialect_point']}> matched={row['region_matched']}")

    print("== 3. 确认导入 ==")
    r = requests.post(
        f"{BASE}/api/excel/import",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"filename": "河北省词表.xlsx", "mapping": pv["mapping"], "rows": pv["rows"]},
    )
    imp = r.json()
    check("导入成功 7 条", imp["success_count"] == 7, f"{imp}")
    check("导入无失败", imp["fail_count"] == 0, f"{imp}")

    print("== 4. 词条查询与区划回填 ==")
    r = requests.get(f"{BASE}/api/words", headers={"Authorization": f"Bearer {admin_token}"}, params={"province_code": "13"})
    words = r.json()
    check("河北省词条 7 条", words["total"] == 7, f"total={words['total']}")
    by_content = {w["content"]: w for w in words["items"]}
    w = by_content.get("咋整")
    check("'咋整' 回填 石家庄/长安区", w and w["city_code"] == "1301" and w["district_code"] == "130102", f"{w}")
    w = by_content.get("夜个儿")
    check("'夜个儿' 回填 邯郸/武安市", w and w["city_code"] == "1304" and w["district_code"] == "130481", f"{w}")
    w = by_content.get("忒好")
    check("'忒好' 文件名兜底为河北省", w and w["province_code"] == "13" and w["city_code"] is None, f"{w}")

    print("== 5. 关键字/市 筛选 ==")
    r = requests.get(f"{BASE}/api/words", headers={"Authorization": f"Bearer {admin_token}"}, params={"keyword": "晌午"})
    check("关键字筛选", r.json()["total"] == 1)
    r = requests.get(f"{BASE}/api/words", headers={"Authorization": f"Bearer {admin_token}"}, params={"city_code": "1301"})
    check("石家庄市筛选", r.json()["total"] == 2, f"total={r.json()['total']}")

    print("== 6. 创建任务包并发布 ==")
    word_ids = [w["id"] for w in words["items"] if w["content"] != "忒好"]
    r = requests.post(
        f"{BASE}/api/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "河北省核心词任务", "province_code": "13", "required_audio_count": 30, "word_ids": word_ids},
    )
    task = r.json()
    check("任务创建", task.get("id") is not None and task["word_count"] == 6, f"{task}")
    tid = task["id"]
    r = requests.post(f"{BASE}/api/tasks/{tid}/publish", headers={"Authorization": f"Bearer {admin_token}"})
    check("任务发布", r.json().get("status") == "published", f"{r.text}")

    r = requests.get(f"{BASE}/api/tasks", headers={"Authorization": f"Bearer {admin_token}"})
    check("任务列表", r.json()["total"] == 1)

    print("== 7. 省管理员权限隔离 ==")
    r = requests.get(f"{BASE}/api/words", headers={"Authorization": f"Bearer {hebei_token}"}, params={"province_code": "11"})
    scoped = r.json()
    check("河北管理员请求北京词被钳制为本省", scoped["total"] == 7, f"total={scoped['total']}")
    r = requests.post(
        f"{BASE}/api/tasks",
        headers={"Authorization": f"Bearer {hebei_token}"},
        json={"name": "越权任务", "province_code": "11", "word_ids": []},
    )
    check("河北管理员不能给北京建任务", r.status_code == 403, f"status={r.status_code}")
    r = requests.get(f"{BASE}/api/users", headers={"Authorization": f"Bearer {hebei_token}"})
    check("省管理员无用户管理权限", r.status_code == 403, f"status={r.status_code}")

print(f"\n结果: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
