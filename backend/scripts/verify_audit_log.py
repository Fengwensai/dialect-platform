"""操作审计日志专项验证（进程内 TestClient）。

覆盖：
- 关键写操作落库：发布/关闭/重新打开/删除任务、审核通过/驳回/批量/重置/删除录音、
  删除/合并发音人、删除/合并词条、管理员增删改、删除团队码、解绑领取、导入词表
- 日志字段：admin_id / admin_name / action / target_type / target_id / summary / detail / ip 非空
- 查询端点 GET /api/audit-logs：未登录 401、省管 403、分页/关键词/操作/管理员/时间区间/倒序
- 边界：start>end → 422

用法: ./.venv/Scripts/python.exe scripts/verify_audit_log.py
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
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402
from app.models.team_code import TeamCode  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_audit_log.txt")
results = []
HB_PROV, HB_CITY = "13", "1101"
now = datetime.now(timezone.utc)


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def main():
    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    max_id_before = db.query(func.max(AdminOperationLog.id)).scalar() or 0
    try:
        # —— 0. 登录超管 + 建省管理员（403 用，不落审计）——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("超管登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}
        prov_admin = AdminUser(username="verify_audit_p", password_hash=hash_password("admin123"),
                               name="审计验证省管", role="province_admin", province_code=HB_PROV)
        db.add(prov_admin)
        db.commit()
        PROV = {"Authorization": "Bearer " + create_access_token({"admin_id": prov_admin.id})}

        # —— 1. 种子：词条 ——
        def make_word(code, content):
            w = WordLibrary(code=code, dialect_point="测试点", content=content,
                            example_sentence="测试。", province_code=HB_PROV, status="active")
            db.add(w)
            db.flush()
            return w

        w1 = make_word("VFY-AU-HB1", "审计词1")      # merge 保留方
        w2 = make_word("VFY-AU-HB2", "审计词2")      # merge 移除方
        w3 = make_word("VFY-AU-HB3", "审计词3录音")   # rec2/rec3 用
        w4 = make_word("VFY-AU-HB4", "审计词4删除")   # 删除测试用（无引用）
        db.commit()

        def make_task(name, wids):
            r = c.post("/api/tasks", headers=SUPER, json={
                "name": name, "province_code": HB_PROV, "city_code": HB_CITY,
                "team_code": None, "required_audio_count": 10, "claim_limit": 5,
                "word_ids": wids, "is_demo": False})
            assert r.status_code == 200, f"建任务失败 {r.status_code} {r.text[:200]}"
            return r.json()["id"]

        # —— 2. 任务A：状态流转 + 删除（先建先删，释放 w1/w2 占用）——
        t1 = make_task("验证审计任务A", [w1.id, w2.id])
        check("建任务本身不落审计（首个审计操作前日志数不变）",
              (db.query(func.max(AdminOperationLog.id)).scalar() or 0) == max_id_before)
        c.post(f"/api/tasks/{t1}/publish", headers=SUPER)          # 发布任务
        c.post(f"/api/tasks/{t1}/close", headers=SUPER)            # 关闭任务
        c.post(f"/api/tasks/{t1}/reopen", headers=SUPER)           # 重新打开任务
        c.delete(f"/api/tasks/{t1}", headers=SUPER)                # 删除任务

        # —— 3. 任务B + 发音人 + 录音 + 团队码 + 领取 ——
        t2 = make_task("验证审计任务B", [w1.id, w3.id])   # 录音/领取挂这里

        def make_sp(dev, nick):
            sp = Speaker(device_id=dev, nickname=nick, province_code=HB_PROV,
                         gender="male", age_bracket="age18_30", openid="va_" + dev)
            db.add(sp)
            db.flush()
            return sp

        sp1 = make_sp("verify_audit_sp1", "审计删除发音人")   # 删除目标（无录音）
        sp_k = make_sp("verify_audit_keep", "审计合并留")     # merge keep
        sp_r = make_sp("verify_audit_remove", "审计合并去")   # merge remove
        sp_rec = make_sp("verify_audit_rec", "审计录音发音人") # 录音持有者
        sp_claim = make_sp("verify_audit_claim", "审计领取发音人")  # 解绑用

        def rec(sp, t, w):
            rr = Recording(task_id=t, word_id=w, speaker_id=sp.id, audio_url="verify/audit_log.wav",
                           audio_duration=1000, file_size=21, status="pending")
            db.add(rr)
            db.flush()
            return rr

        rec1 = rec(sp_rec, t2, w1.id)   # 审核状态机：驳回→重置→通过→改判驳回→删除
        rec2 = rec(sp_rec, t2, w3.id)   # 批量通过用
        rec3 = rec(sp_claim, t2, w3.id) # 批量通过用
        db.commit()

        # 团队码 + 领取（DB 建，走 API 删）
        tc = TeamCode(code="VFY-AU-T", name="审计团队", province_code=HB_PROV,
                      city_code=HB_CITY, created_by=1)
        db.add(tc)
        db.flush()
        claim = TaskClaim(task_id=t2, word_id=w1.id, speaker_id=sp_claim.id, claimed_at=now)
        db.add(claim)
        db.commit()

        # =============== 触发被审操作（全为超管，admin_id=1） ===============
        c.post(f"/api/review/recordings/{rec1.id}/verdict",
               headers=SUPER, json={"approved": False, "note": "噪音大"})     # 审核驳回
        c.post(f"/api/review/recordings/{rec1.id}/reset", headers=SUPER)      # 重置为待审
        c.post(f"/api/review/recordings/{rec1.id}/verdict",
               headers=SUPER, json={"approved": True})                        # 审核通过
        c.post(f"/api/review/recordings/{rec1.id}/verdict",
               headers=SUPER, json={"approved": False, "note": "改判"})       # 审核驳回(改判)
        r = c.post("/api/review/batch-verdict", headers=SUPER,
                   json={"recording_ids": [rec2.id, rec3.id], "approved": True})  # 批量审核通过
        check("批量审核 2 条 processed=2", r.status_code == 200 and r.json()["processed"] == 2,
              str(r.status_code) + " " + r.text[:120])
        c.delete(f"/api/review/recordings/{rec1.id}", headers=SUPER)  # 删除录音（rejected 可删）

        c.delete(f"/api/speakers/{sp1.id}", headers=SUPER)   # 删除发音人
        c.post("/api/speakers/merge", headers=SUPER,
               json={"keep_speaker_id": sp_k.id, "remove_speaker_id": sp_r.id})   # 合并发音人
        c.post("/api/words/merge", headers=SUPER,
               json={"keep_word_id": w1.id, "remove_word_id": w2.id})             # 合并词条
        c.delete(f"/api/words/{w4.id}", headers=SUPER)      # 删除词条

        r = c.post("/api/users", headers=SUPER, json={
            "username": "verify_audit_a2", "name": "审计新管理员",
            "password": "admin123", "role": "province_admin", "province_code": HB_PROV})
        a2 = r.json()
        c.patch(f"/api/users/{a2['id']}", headers=SUPER, json={"name": "审计新管理员改"})  # 修改管理员
        c.delete(f"/api/users/{a2['id']}", headers=SUPER)     # 删除管理员

        c.delete(f"/api/team-codes/{tc.id}", headers=SUPER)   # 删除团队码
        c.delete(f"/api/tasks/{t2}/claims/{claim.id}", headers=SUPER)   # 解绑领取
        c.post("/api/excel/import", headers=SUPER, json={
            "filename": "河北省审计导入.xlsx",
            "rows": [{"row_index": 1, "code": "VFY-AU-X1", "dialect_point": "石家庄",
                      "content": "审计导入词"}]})                        # 导入词表

        # =============== 断言落库 ===============
        logs = (db.query(AdminOperationLog)
                .filter(AdminOperationLog.id > max_id_before)
                .order_by(AdminOperationLog.id).all())
        check("共落库 20 条审计日志", len(logs) == 20, f"{len(logs)}")

        def find(action, target_id=None):
            for x in logs:
                if x.action == action and (target_id is None or str(x.target_id) == str(target_id)):
                    return x
            return None

        check("任务：发布/关闭/重新打开/删除 各 1 条",
              all(find(a, t1) for a in ["发布任务", "关闭任务", "重新打开任务", "删除任务"]))
        check("录音：通过/驳回(2)/重置/删除 各就位",
              find("审核通过", rec1.id) and find("审核驳回", rec1.id)
              and find("重置为待审", rec1.id) and find("删除录音", rec1.id))
        b = find("批量审核通过")
        check("批量审核 detail.processed=2", b is not None and b.detail and b.detail.get("processed") == 2,
              f"{b.detail if b else None}")
        check("删除发音人 落库", find("删除发音人", sp1.id) is not None)
        m = find("合并发音人", sp_k.id)
        check("合并发音人 摘要含 remove 方", m is not None and f"#{sp_r.id}" in m.summary,
              f"{m.summary if m else None}")
        wm = find("合并词条", w1.id)
        check("合并词条 摘要含 remove 方", wm is not None and f"#{w2.id}" in wm.summary,
              f"{wm.summary if wm else None}")
        check("删除词条 落库", find("删除词条", w4.id) is not None)
        check("创建/修改/删除管理员 各就位",
              find("创建管理员", a2["id"]) and find("修改管理员", a2["id"]) and find("删除管理员", a2["id"]))
        cu = find("创建管理员", a2["id"])
        check("创建管理员 摘要含姓名+角色", cu is not None and "审计新管理员" in cu.summary and "province_admin" in cu.summary,
              f"{cu.summary if cu else None}")
        mu = find("修改管理员", a2["id"])
        check("修改管理员 detail 含 name", mu is not None and mu.detail and "name" in mu.detail,
              f"{mu.detail if mu else None}")
        check("删除团队码 摘要含码", find("删除团队码", tc.id) is not None
              and "VFY-AU-T" in find("删除团队码", tc.id).summary)
        check("解绑领取 落库且摘要含词条", find("解绑领取", claim.id) is not None
              and f"词条 #{w1.id}" in find("解绑领取", claim.id).summary)
        imp = find("导入词表")
        check("导入词表 摘要成功 1", imp is not None and "成功 1" in imp.summary,
              f"{imp.summary if imp else None}")

        check("全部日志 admin_id=1 / admin_name 非空 / ip 非空",
              all(x.admin_id == 1 and x.admin_name and x.ip for x in logs))
        check("ip 捕获 TestClient 地址", all(x.ip == "testclient" for x in logs))
        check("target_id 非空条目均命中测试目标",
              all(str(x.target_id) in {str(t1), str(t2), str(rec1.id), str(rec2.id), str(rec3.id),
                                       str(sp1.id), str(sp_k.id), str(w1.id), str(w2.id), str(w4.id),
                                       str(a2["id"]), str(tc.id), str(claim.id)} or x.target_id is None
                  for x in logs))

        # =============== 查询端点 ===============
        def q(**params):
            return c.get("/api/audit-logs", headers=SUPER, params=params)

        r = c.get("/api/audit-logs")
        check("未登录 → 401", r.status_code == 401, str(r.status_code))
        r = c.get("/api/audit-logs", headers=PROV)
        check("省管访问 → 403", r.status_code == 403, str(r.status_code))

        r = q()
        body = r.json()
        check("默认查询 total=20", r.status_code == 200 and body["total"] == 20,
              f"{r.status_code} total={body.get('total')}")
        check("默认按时间倒序（首条=导入词表）", body["items"][0]["action"] == "导入词表",
              f"{body['items'][0]['action']}")
        check("默认每页 20 条", len(body["items"]) == 20, f"{len(body['items'])}")

        r = q(page_size=5)
        check("page_size=5 返回 5 条", len(r.json()["items"]) == 5, f"{len(r.json()['items'])}")

        r = q(keyword="验证审计任务")
        kb = r.json()
        check("keyword=验证审计任务 → 4 条（任务四态）",
              r.status_code == 200 and kb["total"] == 4,
              f"total={kb.get('total')}")
        check("keyword 命中摘要", all("验证审计任务" in (i["summary"] or "") for i in kb["items"]))
        r = q(keyword="超级管理员")
        check("keyword 匹配管理员名 → 20 条（全部）", r.json()["total"] == 20,
              f"{r.json().get('total')}")

        r = q(action="审核驳回")
        ab = r.json()
        check("action=审核驳回 → 2 条（首审+改判）",
              ab["total"] == 2 and all(i["target_id"] == str(rec1.id) for i in ab["items"]),
              f"total={ab.get('total')}")

        r = q(admin_id=1)
        check("admin_id=1 → 20 条", r.json()["total"] == 20, f"{r.json().get('total')}")

        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        r = q(start=past.isoformat(), end=(past + timedelta(days=1)).isoformat())
        check("2000 年区间 → 0 条", r.json()["total"] == 0, f"{r.json().get('total')}")
        r = q(start=(now - timedelta(days=1)).isoformat(), end=(now + timedelta(days=1)).isoformat())
        check("近两日区间 → 20 条", r.json()["total"] == 20, f"{r.json().get('total')}")
        r = q(start=now.isoformat(), end=(now - timedelta(days=1)).isoformat())
        check("start>end → 422", r.status_code == 422, str(r.status_code))

        # =============== 清理 ===============
        db.query(AdminOperationLog).filter(AdminOperationLog.id > max_id_before).delete(synchronize_session=False)
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
    # 审计日志表为本次新增，本地开发库中除本测试外无真实日志 → 全清，避免跨次残留污染断言
    db.query(AdminOperationLog).delete(synchronize_session=False)
    # 发音人（sp1 已删、sp_r 已合并）→ 连带录音/领取/协议
    sps = db.query(Speaker).filter(Speaker.device_id.like("verify_audit%")).all()
    sp_ids = [s.id for s in sps]
    if sp_ids:
        db.query(Recording).filter(Recording.speaker_id.in_(sp_ids)).delete(synchronize_session=False)
        db.query(TaskClaim).filter(TaskClaim.speaker_id.in_(sp_ids)).delete(synchronize_session=False)
    # 任务（t1 已删）连带词条关联
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证审计任务%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete(synchronize_session=False)
        db.query(TaskClaim).filter(TaskClaim.task_id == t.id).delete(synchronize_session=False)
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete(synchronize_session=False)
        db.delete(t)
    # 剩余录音（rec2/rec3 批量通过后仍存在）
    db.query(Recording).filter(Recording.audio_url == "verify/audit_log.wav").delete(synchronize_session=False)
    for s in sps:
        db.delete(s)
    # 词条（w1 保留 / w2、w4 已删；VFY-AU 前缀全覆盖）
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY-AU%")).delete(synchronize_session=False)
    db.query(TeamCode).filter(TeamCode.code == "VFY-AU-T").delete(synchronize_session=False)
    db.query(TaskClaim).filter(TaskClaim.task_id.in_(
        db.query(TaskBatch.id).filter(TaskBatch.name.like("验证审计任务%")))).delete(synchronize_session=False)
    db.query(AdminUser).filter(AdminUser.username.in_(["verify_audit_p", "verify_audit_a2"])).delete(synchronize_session=False)
    db.commit()


if __name__ == "__main__":
    main()
