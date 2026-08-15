"""审核增强专项验证：批量审核 + 列表筛选增强（进程内 TestClient）。

覆盖：
- 批量通过/驳回：只处理 pending，已审过的跳过；mixed 返回 processed/skipped
- 越省跳过：省管理员批量选北京录音 → 跳过；全越省 → 400
- 边界：空列表 400、不存在 404、全已审 400
- 列表筛选：keyword（发音人昵称/词条内容）、province_code、status
- 列表排序：pending_first（默认）/created/duration/reviewed（已审靠前）
- 非法 status / sort_by → 422

用法: ./.venv/Scripts/python.exe scripts/verify_review_batch.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_review_batch.txt")
results = []
HB_PROV, BJ_PROV = "13", "11"


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def main():
    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    now = datetime.now(timezone.utc)
    try:
        # —— 0. 登录超管 + 建省管理员 ——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("超管登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}
        hb_admin = AdminUser(username="verify_review_admin", password_hash=hash_password("admin123"),
                             name="审核验证省管", role="province_admin", province_code=HB_PROV)
        db.add(hb_admin)
        db.commit()
        HB = {"Authorization": "Bearer " + create_access_token({"admin_id": hb_admin.id})}

        # —— 1. 词条 + 任务（河北 + 北京）——
        hb_w1 = WordLibrary(code="VFY-RV-HB1", dialect_point="测试点", content="批量审核河北词1",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        hb_w2 = WordLibrary(code="VFY-RV-HB2", dialect_point="测试点", content="批量审核河北词2",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        bj_w1 = WordLibrary(code="VFY-RV-BJ1", dialect_point="测试点", content="批量审核北京词1",
                            example_sentence="测试。", province_code=BJ_PROV, status="active")
        db.add_all([hb_w1, hb_w2, bj_w1])
        db.flush()

        def make_task(name, prov, wids):
            t = TaskBatch(name=name, province_code=prov, required_audio_count=30,
                          claim_limit=10, status="published", created_by=1)
            db.add(t)
            db.flush()
            for w in wids:
                db.add(TaskBatchItem(task_batch_id=t.id, word_id=w.id))
            return t

        task_hb = make_task("验证批量-河北", HB_PROV, [hb_w1, hb_w2])
        task_bj = make_task("验证批量-北京", BJ_PROV, [bj_w1])
        db.commit()

        # —— 2. 发音人 + 录音 6 条 ——
        def make_sp(dev, nick, prov):
            sp = Speaker(device_id=dev, nickname=nick, province_code=prov,
                         gender="male", age_bracket="age18_30", openid="vr_" + dev)
            db.add(sp)
            db.flush()
            return sp

        sp_hb1 = make_sp("verify_rev_hb1", "批量河北甲", HB_PROV)
        sp_hb2 = make_sp("verify_rev_hb2", "批量河北乙", HB_PROV)
        sp_bj = make_sp("verify_rev_bj1", "批量北京", BJ_PROV)

        def rec(sp, t, w, status, dur, created, reviewed_at=None):
            r = Recording(task_id=t.id, word_id=w.id, speaker_id=sp.id,
                          audio_url="verify/review_batch.wav", audio_duration=dur,
                          file_size=1000, status=status, created_at=created,
                          reviewed_at=reviewed_at)
            db.add(r)
            db.flush()
            return r

        r1 = rec(sp_hb1, task_hb, hb_w1, "pending", 1000, now + timedelta(minutes=1))
        r2 = rec(sp_hb1, task_hb, hb_w2, "pending", 2000, now + timedelta(minutes=2))
        r3 = rec(sp_hb2, task_hb, hb_w1, "pending", 3000, now + timedelta(minutes=3))
        r4 = rec(sp_bj, task_bj, bj_w1, "pending", 4000, now + timedelta(minutes=4))
        r5 = rec(sp_hb2, task_hb, hb_w2, "approved", 5000, now, now + timedelta(minutes=30))
        r6 = rec(sp_bj, task_bj, bj_w1, "approved", 6000, now - timedelta(minutes=1), now + timedelta(minutes=40))
        db.commit()
        check("种子：3 发音人 + 6 录音", all(x.id for x in [r1, r2, r3, r4, r5, r6]))

        # ================= 列表筛选/排序 =================
        def lst(token, **params):
            return c.get("/api/review/recordings", headers=token, params=params)

        # 默认状态（不传 status）= 全部 6
        r = lst(SUPER)
        check("列表默认全部 6 条", r.status_code == 200 and r.json()["total"] == 6, f"{r.json().get('total')}")
        # status=pending → 4
        r = lst(SUPER, status="pending")
        check("status=pending → 4", r.json()["total"] == 4, f"{r.json().get('total')}")
        # status=approved → 2
        r = lst(SUPER, status="approved")
        check("status=approved → 2", r.json()["total"] == 2, f"{r.json().get('total')}")
        # keyword 发音人昵称 → r1/r2（sp_hb1）
        r = lst(SUPER, keyword="河北甲", status="pending")
        ids = {x["id"] for x in r.json()["items"]}
        check("keyword=河北甲 → r1+r2", r.json()["total"] == 2 and ids == {r1.id, r2.id}, f"{sorted(ids)}")
        # keyword 词条内容 → r2（pending 下）
        r = lst(SUPER, keyword="河北词2", status="pending")
        check("keyword=河北词2 → r2", r.json()["total"] == 1 and r.json()["items"][0]["id"] == r2.id,
              f"{r.json().get('total')}")
        # province_code=11 → 北京
        r = lst(SUPER, province_code=BJ_PROV, status="pending")
        check("province_code=11 → r4", r.json()["total"] == 1 and r.json()["items"][0]["id"] == r4.id,
              f"{r.json().get('total')}")
        # 非法 status / sort_by → 422
        r = lst(SUPER, status="x")
        check("非法 status → 422", r.status_code == 422, str(r.status_code))
        r = lst(SUPER, sort_by="bad")
        check("非法 sort_by → 422", r.status_code == 422, str(r.status_code))

        # —— 排序相对顺序 ——
        def first_id(**params):
            return lst(SUPER, **params).json()["items"][0]["id"]

        check("sort=duration 最长优先 → r4(4000ms)",
              first_id(sort_by="duration", status="pending") == r4.id, f"{first_id(sort_by='duration', status='pending')}")
        check("sort=created 最新优先 → r4(t+4)",
              first_id(sort_by="created", status="pending") == r4.id, f"{first_id(sort_by='created', status='pending')}")
        check("sort=reviewed 最近审核优先 → r6(+40min)",
              first_id(sort_by="reviewed", status="approved") == r6.id,
              f"{first_id(sort_by='reviewed', status='approved')}")
        check("sort=pending_first 待审优先 + 最新在前（默认）→ r4",
              first_id(status="pending") == r4.id, f"{first_id(status='pending')}")

        # —— 省管理员列表钳制 ——
        r = lst(HB, status="pending")
        ids = {x["id"] for x in r.json()["items"]}
        check("省管列表仅河北 3 条", r.json()["total"] == 3 and ids == {r1.id, r2.id, r3.id}, f"{sorted(ids)}")

        # ================= 批量审核 =================
        # 批量通过 3 条 pending → processed=3
        r = c.post("/api/review/batch-verdict", headers=SUPER,
                   json={"recording_ids": [r1.id, r2.id, r3.id], "approved": True})
        body = r.json()
        check("批量通过 3 条 → processed=3", r.status_code == 200 and body["processed"] == 3
              and body["skipped"] == 0, str(r.status_code) + " " + str(body))
        db.refresh(r1)
        check("r1 已通过", r1.status == "approved" and r1.reviewed_by == 1, f"{r1.status}")

        # mixed：r1(已通过) + r4(pending) 驳回 → processed=1 / skipped=1，note+原因落库（重复 key 去重）
        r = c.post("/api/review/batch-verdict", headers=SUPER,
                   json={"recording_ids": [r1.id, r4.id], "approved": False,
                         "reasons": ["noise", "misread", "noise"], "note": "噪音大"})
        body = r.json()
        check("mixed 批量驳回 → processed=1 skipped=1",
              r.status_code == 200 and body["processed"] == 1 and body["skipped"] == 1,
              str(r.status_code) + " " + str(body))
        db.refresh(r4)
        check("r4 已驳回 + note/原因 落库（去重）",
              r4.status == "rejected" and r4.review_note == "噪音大" and r4.reject_reasons == "noise,misread",
              f"{r4.status} note={r4.review_note} reasons={r4.reject_reasons}")

        # 全已审 → 400
        r = c.post("/api/review/batch-verdict", headers=SUPER,
                   json={"recording_ids": [r1.id, r5.id], "approved": True})
        check("全已审 → 400 均无需审核", r.status_code == 400 and "均无需审核" in str(r.json()),
              str(r.status_code) + " " + r.text[:80])
        # 空列表 → 400
        r = c.post("/api/review/batch-verdict", headers=SUPER, json={"recording_ids": [], "approved": True})
        check("空列表 → 400 未选择", r.status_code == 400, str(r.status_code))
        # 不存在 → 404
        r = c.post("/api/review/batch-verdict", headers=SUPER, json={"recording_ids": [999999], "approved": True})
        check("不存在的录音 → 404", r.status_code == 404, str(r.status_code))

        # —— 单条驳回 + 原因（后台完善 2）——
        r9 = rec(sp_hb1, task_hb, hb_w2, "pending", 9000, now + timedelta(hours=2))
        db.commit()
        r = c.post(f"/api/review/recordings/{r9.id}/verdict", headers=SUPER,
                   json={"approved": False, "reasons": ["too_quiet"], "note": "太轻"})
        body = r.json()
        check("单条驳回带原因 → 200 + 字段透出",
              r.status_code == 200 and body["status"] == "rejected" and body["reject_reasons"] == "too_quiet"
              and body["review_note"] == "太轻",
              str(r.status_code) + " " + r.text[:120])
        db.refresh(r9)
        check("r9 原因落库", r9.reject_reasons == "too_quiet", f"{r9.reject_reasons}")
        # 通过时不带原因
        r10 = rec(sp_hb1, task_hb, hb_w1, "pending", 9500, now + timedelta(hours=2))
        db.commit()
        r = c.post(f"/api/review/recordings/{r10.id}/verdict", headers=SUPER, json={"approved": True})
        db.refresh(r10)
        check("通过时 reasons 不落库", r.status_code == 200 and r10.reject_reasons is None,
              f"reasons={r10.reject_reasons}")
        # 非法原因 → 422
        r = c.post(f"/api/review/recordings/{r9.id}/verdict", headers=SUPER,
                   json={"approved": False, "reasons": ["bogus"]})
        check("非法原因 → 422", r.status_code == 422 and "bogus" in r.text, str(r.status_code) + " " + r.text[:100])

        # —— 省管理员：新建 2 条 pending（河北/北京各一）验证越省跳过 ——
        r7 = rec(sp_hb1, task_hb, hb_w1, "pending", 7000, now + timedelta(hours=1))
        r8 = rec(sp_bj, task_bj, bj_w1, "pending", 8000, now + timedelta(hours=1))
        db.commit()
        r = c.post("/api/review/batch-verdict", headers=HB,
                   json={"recording_ids": [r7.id, r8.id], "approved": True})
        body = r.json()
        check("省管批量 → 只处理河北 processed=1 skipped=1",
              r.status_code == 200 and body["processed"] == 1 and body["skipped"] == 1,
              str(r.status_code) + " " + str(body))
        db.refresh(r7)
        db.refresh(r8)
        check("r7(河北)已通过 / r8(北京)未动", r7.status == "approved" and r8.status == "pending",
              f"r7={r7.status} r8={r8.status}")
        r = c.post("/api/review/batch-verdict", headers=HB, json={"recording_ids": [r8.id], "approved": True})
        check("省管全越省 → 400", r.status_code == 400, str(r.status_code) + " " + r.text[:80])

        cleanup(db)
        check("清理种子数据", True)
    finally:
        db.close()

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    passed = sum(1 for x in results if x.startswith("[PASS]"))
    failed = sum(1 for x in results if x.startswith("[FAIL]"))
    print(f"RESULT: {passed} PASS / {failed} FAIL (详见 {OUT})")


def cleanup(db):
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证批量-%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    for sp in db.query(Speaker).filter(Speaker.device_id.like("verify_rev%")).all():
        db.query(Recording).filter(Recording.speaker_id == sp.id).delete()
        db.delete(sp)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY-RV%")).delete()
    db.query(AdminUser).filter(AdminUser.username == "verify_review_admin").delete()
    db.commit()


if __name__ == "__main__":
    main()
