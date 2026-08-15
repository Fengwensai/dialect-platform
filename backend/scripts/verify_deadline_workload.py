"""任务截止时间 + 到期清理 + 审核工作量报表专项验证（进程内 TestClient）。

覆盖（后台完善 9）：
- 权限：workload 未登录 401、省管 403（superOnly）；cleanup-expired 未登录 401（省管可用）
- 截止时间：创建/编辑带 deadline_at 回传、发布后过期→expired、未来→非 expired、
  已完成优先于到期（completed）、关闭→archived、草稿过期不标、编辑可设/清空
- cleanup-expired：一键关闭所有「已发布且已过截止」任务（相对直接计数）+ 审计「到期自动关闭」
  + 省管钳制本省
- dashboard/health.expired_tasks：超管全量、省管本省
- workload：按 reviewed_by 聚合条数/通过率/驳回原因；窗口外不计入；days 生效

用法: ./.venv/Scripts/python.exe scripts/verify_deadline_workload.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.audit_log import AdminOperationLog  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_deadline_workload.txt")
results = []
SENTINEL = 910000  # 测试哨兵 id（远超真实 id）
HB = "13"  # 河北（种子团队省）
BJ = "11"  # 北京
NOW = datetime.now(timezone.utc)


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def make_task(db, name, province, deadline, status="draft", word=None):
    """直接落库造任务（跳过 API，供 cleanup/health 用），flush 后返回。"""
    t = TaskBatch(name=name, province_code=province, required_audio_count=30,
                  claim_limit=10, status=status, created_by=1, deadline_at=deadline)
    db.add(t)
    db.flush()
    if word:
        db.add(TaskBatchItem(task_batch_id=t.id, word_id=word.id))
    return t


def find_task(c, headers, name):
    items = c.get("/api/tasks", headers=headers, params={"page_size": 200}).json()["items"]
    return next((it for it in items if it["name"] == name), None)


def direct_expired(db, province=None):
    """已发布且已过截止时间的任务数（相对计数，超管/省管钳制）。"""
    q = (db.query(func.count(TaskBatch.id))
         .filter(TaskBatch.status == "published",
                 TaskBatch.deadline_at.isnot(None),
                 TaskBatch.deadline_at < datetime.now(timezone.utc)))
    if province:
        q = q.filter(TaskBatch.province_code == province)
    return q.scalar() or 0


def cleanup(db):
    """删除测试数据：VFY-DL 任务（连带条目/录音）+ 哨兵录音 + VFY-DL 词条 + 两个测试管理员。"""
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("VFY-DL-%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete(synchronize_session=False)
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete(synchronize_session=False)
        db.delete(t)
    db.query(Recording).filter(Recording.word_id >= SENTINEL).delete(synchronize_session=False)
    for w in db.query(WordLibrary).filter(WordLibrary.code.like("VFY-DL-%")).all():
        db.query(TaskBatchItem).filter(TaskBatchItem.word_id == w.id).delete(synchronize_session=False)
        db.delete(w)
    db.query(AdminUser).filter(
        AdminUser.username.in_(["verify_dl_bj", "verify_dl_auditor"])
    ).delete(synchronize_session=False)
    db.commit()


def main():
    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    try:
        # —— 0. 登录超管 + 建省管理员（北京）+ 审核员 B（无存量）——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("超管登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}
        bj_admin = AdminUser(username="verify_dl_bj", password_hash=hash_password("admin123"),
                             name="截止省管", role="province_admin", province_code=BJ)
        db.add(bj_admin)
        auditor = AdminUser(username="verify_dl_auditor", password_hash=hash_password("admin123"),
                            name="工作量审核员B")
        db.add(auditor)
        db.commit()
        BJH = {"Authorization": "Bearer " + create_access_token({"admin_id": bj_admin.id})}

        # —— 1. 权限 ——
        check("workload 未登录 401", c.get("/api/audit-logs/workload").status_code == 401)
        check("workload 省管 403", c.get("/api/audit-logs/workload", headers=BJH).status_code == 403)
        check("cleanup-expired 未登录 401", c.post("/api/tasks/cleanup-expired").status_code == 401)

        # —— 2. 截止时间：创建/编辑回传 + 状态判定 ——
        fut = (NOW + timedelta(days=1)).isoformat()
        past = (NOW - timedelta(days=1)).isoformat()

        # A1：未来截止，草稿创建 → 回传
        r = c.post("/api/tasks", json={"name": "VFY-DL-FUTURE", "province_code": HB,
                                       "required_audio_count": 30, "claim_limit": 10,
                                       "word_ids": [], "deadline_at": fut}, headers=SUPER)
        check("创建带截止回传", r.status_code == 200 and r.json().get("deadline_at"), str(r.status_code))
        a1 = r.json()["id"]
        check("创建后为草稿", r.json()["status"] == "draft")
        r = c.post(f"/api/tasks/{a1}/publish", headers=SUPER)
        check("发布未来截止非 expired", r.json()["completion_status"] != "expired",
              r.json()["completion_status"])

        # A2：过去截止，发布 → expired；关闭 → archived
        r = c.post("/api/tasks", json={"name": "VFY-DL-EXPIRED", "province_code": HB,
                                       "required_audio_count": 30, "claim_limit": 10,
                                       "word_ids": [], "deadline_at": past}, headers=SUPER)
        a2 = r.json()["id"]
        c.post(f"/api/tasks/{a2}/publish", headers=SUPER)
        it = find_task(c, SUPER, "VFY-DL-EXPIRED")
        check("发布后过期 → expired", it and it["completion_status"] == "expired",
              it and it["completion_status"])
        c.post(f"/api/tasks/{a2}/close", headers=SUPER)
        it = find_task(c, SUPER, "VFY-DL-EXPIRED")
        check("关闭过期 → archived", it and it["completion_status"] == "archived",
              it and it["completion_status"])

        # A3：过去截止但已录 100% → completed 优先
        w3 = WordLibrary(code="VFY-DL-W3", dialect_point="测试点", content="截止完成词",
                         province_code=HB, status="active")
        db.add(w3)
        db.flush()
        a3 = make_task(db, "VFY-DL-COMPLETED", HB, NOW - timedelta(hours=1),
                       status="published", word=w3)
        db.add(Recording(task_id=a3.id, word_id=w3.id, speaker_id=SENTINEL,
                         audio_url="placeholder.wav", status="approved",
                         reviewed_by=1, reviewed_at=NOW))
        db.commit()
        it = find_task(c, SUPER, "VFY-DL-COMPLETED")
        check("已录100%且过期 → completed 优先",
              it and it["completion_status"] == "completed",
              it and f"{it['completion_status']} rec={it['recorded_count']}/{it['word_count']}")

        # A4：草稿过去截止 → 不标 expired；编辑可设/清空
        r = c.post("/api/tasks", json={"name": "VFY-DL-DRAFT", "province_code": HB,
                                       "required_audio_count": 30, "claim_limit": 10,
                                       "word_ids": [], "deadline_at": past}, headers=SUPER)
        a4 = r.json()["id"]
        it = find_task(c, SUPER, "VFY-DL-DRAFT")
        check("草稿过去截止不标 expired", it and it["completion_status"] == "in_progress",
              it and it["completion_status"])
        r = c.patch(f"/api/tasks/{a4}", json={"deadline_at": fut}, headers=SUPER)
        check("编辑设截止回传", r.status_code == 200 and r.json().get("deadline_at"), str(r.status_code))
        r = c.patch(f"/api/tasks/{a4}", json={"deadline_at": None}, headers=SUPER)
        check("编辑清空截止", r.status_code == 200 and r.json().get("deadline_at") is None,
              str(r.status_code))

        # —— 3. dashboard/health.expired_tasks：超管全量 / 省管本省 ——
        a5 = make_task(db, "VFY-DL-CL1", HB, NOW - timedelta(hours=2), status="published")
        a6 = make_task(db, "VFY-DL-CL2", HB, NOW + timedelta(days=2), status="published")
        a7 = make_task(db, "VFY-DL-CL3", HB, NOW - timedelta(hours=3), status="published")
        a8 = make_task(db, "VFY-DL-CL4", BJ, NOW - timedelta(hours=1), status="published")
        db.commit()
        exp_super = direct_expired(db)
        exp_bj = direct_expired(db, BJ)
        h = c.get("/api/dashboard/health", headers=SUPER).json()
        check("health 含 expired_tasks", "expired_tasks" in h, str(list(h)))
        check("health expired_tasks=全量", h["expired_tasks"] == exp_super,
              f"{h['expired_tasks']} vs {exp_super}")
        h_bj = c.get("/api/dashboard/health", headers=BJH).json()
        check("health 省管 expired_tasks=本省", h_bj["expired_tasks"] == exp_bj,
              f"{h_bj['expired_tasks']} vs {exp_bj}")

        # —— 4. cleanup-expired：省管先（只关本省），超管后（全量），相对直接计数 ——
        before_log = db.query(func.max(AdminOperationLog.id)).scalar() or 0
        exp_bj = direct_expired(db, BJ)
        r = c.post("/api/tasks/cleanup-expired", headers=BJH)
        check("省管清理 200", r.status_code == 200, str(r.status_code))
        check("省管清理 closed=本省过期", r.json()["closed"] == exp_bj,
              f"{r.json()['closed']} vs {exp_bj}")
        t7 = a7  # make_task 返回的是持久化对象，直接用其 status
        check("省管不动河北过期任务", t7.status == "published", t7.status)
        exp_super = direct_expired(db)  # 省管已关北京，重算超管口径
        r = c.post("/api/tasks/cleanup-expired", headers=SUPER)
        check("超管清理 closed=全量过期", r.json()["closed"] == exp_super,
              f"{r.json()['closed']} vs {exp_super}")
        t6 = a6
        check("未来截止任务不受清理", t6.status == "published", t6.status)
        logs = db.query(AdminOperationLog).filter(
            AdminOperationLog.id > before_log,
            AdminOperationLog.action == "到期自动关闭",
        ).count()
        check("审计「到期自动关闭」≥ 关闭总数", logs >= (exp_bj + exp_super), f"{logs}")

        # —— 5. workload：按 reviewed_by 聚合 + 窗口 ——
        # 审核员 B（无存量）：3 条窗口内（2 通过 + 1 驳回 noise,incomplete）+ 1 条窗口外(40 天前)
        for i in range(2):
            db.add(Recording(task_id=SENTINEL, word_id=SENTINEL + i, speaker_id=SENTINEL,
                             audio_url="placeholder.wav", status="approved",
                             reviewed_by=auditor.id, reviewed_at=NOW))
        db.add(Recording(task_id=SENTINEL, word_id=SENTINEL + 2, speaker_id=SENTINEL,
                         audio_url="placeholder.wav", status="rejected",
                         reject_reasons="noise,incomplete", reviewed_by=auditor.id, reviewed_at=NOW))
        db.add(Recording(task_id=SENTINEL, word_id=SENTINEL + 3, speaker_id=SENTINEL,
                         audio_url="placeholder.wav", status="approved", reviewed_by=auditor.id,
                         reviewed_at=NOW - timedelta(days=40)))
        # 超管 admin id=1：1 通过 + 1 驳回 mandarin（允许叠加存量）
        db.add(Recording(task_id=SENTINEL, word_id=SENTINEL + 4, speaker_id=SENTINEL,
                         audio_url="placeholder.wav", status="approved", reviewed_by=1, reviewed_at=NOW))
        db.add(Recording(task_id=SENTINEL, word_id=SENTINEL + 5, speaker_id=SENTINEL,
                         audio_url="placeholder.wav", status="rejected",
                         reject_reasons="mandarin", reviewed_by=1, reviewed_at=NOW))
        db.commit()

        wl7 = c.get("/api/audit-logs/workload", params={"days": 7}, headers=SUPER).json()
        check("workload 结构", set(wl7) == {"items", "total", "days"} and wl7["days"] == 7,
              str(list(wl7)))
        row_b7 = next((x for x in wl7["items"] if x["admin_id"] == auditor.id), None)
        check("B 7天 total=3", row_b7 and row_b7["total"] == 3, str(row_b7))
        check("B 7天 通过/驳回", row_b7 and row_b7["approved"] == 2 and row_b7["rejected"] == 1,
              str(row_b7))
        check("B 通过率=2/3", row_b7 and abs(row_b7["approval_rate"] - 2 / 3) < 1e-9,
              str(row_b7 and row_b7["approval_rate"]))
        b_reasons = {x["key"]: x["count"] for x in row_b7["reasons"]}
        check("B 驳回原因分布", b_reasons.get("noise") == 1 and b_reasons.get("incomplete") == 1,
              str(b_reasons))
        row_s7 = next((x for x in wl7["items"] if x["admin_id"] == 1), None)
        check("超管 7天 ≥ 2（含存量）", row_s7 and row_s7["total"] >= 2
              and row_s7["approved"] >= 1 and row_s7["rejected"] >= 1, str(row_s7))
        s_reasons = {x["key"]: x["count"] for x in row_s7["reasons"]}
        check("超管 驳回原因含 mandarin", s_reasons.get("mandarin", 0) >= 1, str(s_reasons))

        wl90 = c.get("/api/audit-logs/workload", params={"days": 90}, headers=SUPER).json()
        row_b90 = next((x for x in wl90["items"] if x["admin_id"] == auditor.id), None)
        check("B 90天计入窗口外", row_b90 and row_b90["total"] == 4, str(row_b90))

        cleanup(db)
        check("清理种子数据", True)
    finally:
        db.close()

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    passed = sum(1 for x in results if x.startswith("[PASS]"))
    failed = sum(1 for x in results if x.startswith("[FAIL]"))
    print(f"RESULT: {passed} PASS / {failed} FAIL (详见 {OUT})")


if __name__ == "__main__":
    main()
