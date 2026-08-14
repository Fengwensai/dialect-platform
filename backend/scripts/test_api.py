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
    from app.models.task_claim import TaskClaim
    from app.models.word import WordLibrary

    db = SessionLocal()
    try:
        db.query(TaskClaim).delete()
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

    print("== 8. 任务删除（放开状态） ==")
    from app.db import SessionLocal
    from app.models.recording import Recording
    from app.models.speaker import Speaker
    from app.models.task import TaskBatch, TaskBatchItem
    from app.models.task_claim import TaskClaim

    sp_guard_id = None
    sp_bj_id = None

    # 已发布、无录音 → 可删
    r = requests.delete(f"{BASE}/api/tasks/{tid}", headers={"Authorization": f"Bearer {admin_token}"})
    check("已发布无录音任务可删除", r.status_code == 200, f"{r.text}")

    # 建新任务 + 挂一条录音 → 删除被拒（守卫）
    r = requests.post(
        f"{BASE}/api/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "删除守卫测试任务", "province_code": "13", "required_audio_count": 30, "word_ids": [word_ids[0]]},
    )
    tid2 = r.json()["id"]
    requests.post(f"{BASE}/api/tasks/{tid2}/publish", headers={"Authorization": f"Bearer {admin_token}"})
    db = SessionLocal()
    try:
        sp_guard = Speaker(device_id="reg-del-guard", nickname="删除守卫", province_code="13")
        db.add(sp_guard)
        db.flush()
        sp_guard_id = sp_guard.id
        db.add(Recording(
            task_id=tid2, word_id=word_ids[0], speaker_id=sp_guard_id,
            audio_url="/media/recordings/del-guard.wav", audio_duration=1200, file_size=1000,
        ))
        db.commit()
    finally:
        db.close()
    r = requests.delete(f"{BASE}/api/tasks/{tid2}", headers={"Authorization": f"Bearer {admin_token}"})
    check("有录音任务拒绝删除", r.status_code == 400, f"{r.text}")

    print("== 9. 发音人删除 ==")
    # 无录音发音人 → 可删
    db = SessionLocal()
    try:
        sp_del = Speaker(device_id="reg-del-ok", nickname="可删发音人", province_code="13")
        db.add(sp_del)
        db.commit()
        sp_del_id = sp_del.id
    finally:
        db.close()
    r = requests.delete(f"{BASE}/api/speakers/{sp_del_id}", headers={"Authorization": f"Bearer {admin_token}"})
    check("无录音发音人可删除", r.status_code == 200, f"{r.text}")

    # 有录音发音人 → 拒绝
    r = requests.delete(f"{BASE}/api/speakers/{sp_guard_id}", headers={"Authorization": f"Bearer {admin_token}"})
    check("有录音发音人拒绝删除", r.status_code == 400, f"{r.text}")

    # 省管理员删他省发音人 → 403
    db = SessionLocal()
    try:
        sp_bj = Speaker(device_id="reg-del-bj", nickname="北京发音人", province_code="11")
        db.add(sp_bj)
        db.commit()
        sp_bj_id = sp_bj.id
    finally:
        db.close()
    r = requests.delete(f"{BASE}/api/speakers/{sp_bj_id}", headers={"Authorization": f"Bearer {hebei_token}"})
    check("省管理员删除他省发音人被拒", r.status_code == 403, f"{r.text}")

    # 清理自建夹具（ORM 直删，保证可重复运行；删除被拒分支遗留的数据一并清）
    db = SessionLocal()
    try:
        if sp_guard_id:
            db.query(Recording).filter(Recording.speaker_id == sp_guard_id).delete()
            db.query(TaskClaim).filter(TaskClaim.speaker_id == sp_guard_id).delete()
            db.query(Speaker).filter(Speaker.id == sp_guard_id).delete()
        db.query(Recording).filter(Recording.task_id == tid2).delete()
        db.query(TaskClaim).filter(TaskClaim.task_id == tid2).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == tid2).delete()
        db.query(TaskBatch).filter(TaskBatch.id == tid2).delete()
        if sp_bj_id:
            db.query(Speaker).filter(Speaker.id == sp_bj_id).delete()
        db.commit()
    finally:
        db.close()

    print("== 10. 词条占用制 ==")
    # 任务A 用前 5 条词；游离词「忒好」不入任务
    occ_ids = word_ids[:5]
    free_content = "忒好"
    r = requests.post(
        f"{BASE}/api/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "占用制任务A", "province_code": "13", "required_audio_count": 30, "word_ids": occ_ids},
    )
    task_a = r.json()
    occ_tid = task_a["id"]
    check("任务A创建", task_a.get("id") is not None and task_a["word_count"] == 5, f"{task_a}")

    r = requests.get(f"{BASE}/api/words", headers={"Authorization": f"Bearer {admin_token}"}, params={"province_code": "13", "page_size": 100})
    occ = {w["content"]: w["occupied"] for w in r.json()["items"]}
    check("任务A词条 occupied=true", all(occ.get(w["content"]) is True for w in words["items"] if w["id"] in occ_ids), f"{occ}")
    check("游离词条 occupied=false", occ.get(free_content) is False, f"{occ}")

    # 用已占用词条建任务B → 400（占用守卫）
    r = requests.post(
        f"{BASE}/api/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "占用制任务B(应拒)", "province_code": "13", "required_audio_count": 30, "word_ids": [occ_ids[0]]},
    )
    check("已占用词条建任务被拒 400", r.status_code == 400 and "占用" in r.json().get("detail", ""), f"{r.text}")

    # 编辑草稿任务A 保留自己词条 → 200（exclude_task_id 生效）
    r = requests.patch(
        f"{BASE}/api/tasks/{occ_tid}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"word_ids": occ_ids},
    )
    check("编辑草稿保留自己词条 200", r.status_code == 200 and r.json()["word_count"] == 5, f"{r.text}")

    # 发布 → 关闭 → 释放回池 → 原词条可再建任务B
    r = requests.post(f"{BASE}/api/tasks/{occ_tid}/publish", headers={"Authorization": f"Bearer {admin_token}"})
    check("任务A发布", r.status_code == 200, f"{r.text}")
    r = requests.post(f"{BASE}/api/tasks/{occ_tid}/close", headers={"Authorization": f"Bearer {admin_token}"})
    check("任务A关闭", r.status_code == 200, f"{r.text}")
    r = requests.get(f"{BASE}/api/words", headers={"Authorization": f"Bearer {admin_token}"}, params={"province_code": "13", "page_size": 100})
    occ = {w["content"]: w["occupied"] for w in r.json()["items"]}
    check("关闭后词条释放 occupied=false", all(occ.get(w["content"]) is False for w in words["items"]), f"{occ}")

    r = requests.post(
        f"{BASE}/api/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "占用制任务B", "province_code": "13", "required_audio_count": 30, "word_ids": [occ_ids[0]]},
    )
    task_b = r.json()
    occ_tid_b = task_b.get("id")
    check("释放后原词条可再建任务B 200", r.status_code == 200 and occ_tid_b is not None, f"{task_b}")

    # 清理自建夹具
    db = SessionLocal()
    try:
        db.query(TaskClaim).filter(TaskClaim.task_id.in_([occ_tid, occ_tid_b])).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id.in_([occ_tid, occ_tid_b])).delete()
        db.query(TaskBatch).filter(TaskBatch.id.in_([occ_tid, occ_tid_b])).delete()
        db.commit()
    finally:
        db.close()

print(f"\n结果: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
