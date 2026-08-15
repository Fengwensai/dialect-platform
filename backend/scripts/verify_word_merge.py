"""词条查重 + 词条合并专项验证（进程内 TestClient）。

覆盖：
- check-duplicate：精确命中 / 排除自身 / 空 content / 未命中
- merge 词条：Recording / TaskClaim / TaskBatchItem 引用迁移 word_id
- 录音冲突去重：(task, speaker) 冲突按状态保留（approved>rejected>pending）+ 淘汰者存储文件删除；
  含「remove 方胜出」场景（rejected 顶掉 keep 的 pending，胜者归到 keep，不产生孤儿引用）
- claim 冲突：(task, keep) 已领取则删 remove 的
- item 冲突：(task_batch, keep) 已存在则删 remove 的
- keep==remove → 400；词条不存在 → 404；省管越省 → 403；未登录 → 401
- 合并后 remove 词条消失、w2 引用清零
- 词条批量操作（后台完善 6）：batch-status 语义（省管只处理本省、禁用/再禁用 400/启用
  processed+skipped、重复 id 去重、空 400 / 非法 422 / 缺失 404 / 未登录 401）、
  batch-delete（删干净词 + 引用清孤儿 0、有录音全跳过 400、超上限 422）、单条删除有录音 400 加固、
  批量操作审计留痕

用法: ./.venv/Scripts/python.exe scripts/verify_word_merge.py
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.audit_log import AdminOperationLog  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402
from app.services import storage  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_word_merge.txt")
results = []
HB_PROV, BJ_PROV = "13", "11"
now = datetime.now(timezone.utc)


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def main():
    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    try:
        # —— 0. 登录超管 + 建省管理员 ——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("超管登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}
        bj_admin = AdminUser(username="verify_wm_admin", password_hash=hash_password("admin123"),
                             name="词条合并省管", role="province_admin", province_code=BJ_PROV)
        db.add(bj_admin)
        db.commit()
        BJ = {"Authorization": "Bearer " + create_access_token({"admin_id": bj_admin.id})}

        # —— 1. 词条：keep=w1 / remove=w2（河北），bj_w1（北京，403 用）——
        hb_w1 = WordLibrary(code="VFY-WM-HB1", dialect_point="测试点", content="合并保留词",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        hb_w2 = WordLibrary(code="VFY-WM-HB2", dialect_point="测试点", content="合并移除词",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        bj_w1 = WordLibrary(code="VFY-WM-BJ1", dialect_point="测试点", content="合并北京词",
                            example_sentence="测试。", province_code=BJ_PROV, status="active")
        db.add_all([hb_w1, hb_w2, bj_w1])
        db.flush()

        # —— 2. 任务 + 条目（河北）：task_a 含 keep+remove；task_b / task_c 仅 remove ——
        def make_task(name, wid_list):
            t = TaskBatch(name=name, province_code=HB_PROV, required_audio_count=30,
                          claim_limit=10, status="published", created_by=1)
            db.add(t)
            db.flush()
            for wid in wid_list:
                db.add(TaskBatchItem(task_batch_id=t.id, word_id=wid))
            return t

        task_a = make_task("验证词合并-A", [hb_w1.id, hb_w2.id])
        task_b = make_task("验证词合并-B", [hb_w2.id])
        task_c = make_task("验证词合并-C", [hb_w2.id])
        db.commit()

        # —— 3. 发音人 3 人（河北）——
        sps = []
        for i in range(3):
            s = Speaker(device_id=f"verify_wm_sp{i+1}", nickname=f"词合并甲{i+1}",
                        province_code=HB_PROV, gender="male", age_bracket="age18_30",
                        openid=f"vwm{i+1}")
            db.add(s)
            db.flush()
            sps.append(s)
        sp1, sp2, sp3 = sps
        db.commit()

        # —— 4. 录音（真实落盘，供文件清理验证）——
        def rec(sp, t, w, st, label):
            audio_url = f"/media/recordings/{t.id}/{label}.wav"
            storage.put_object(audio_url, b"verify-word-merge")
            rr = Recording(task_id=t.id, word_id=w.id, speaker_id=sp.id, audio_url=audio_url,
                           audio_duration=1000, file_size=21, status=st,
                           content_check_status="media_passed", created_at=now)
            db.add(rr)
            db.flush()
            return rr

        rA = rec(sp1, task_a, hb_w1, "approved", "A")  # keep 方 approved
        rC = rec(sp1, task_a, hb_w2, "rejected", "C")  # (task_a,sp1) 冲突 → rejected 输给 approved，删
        rB = rec(sp3, task_b, hb_w1, "pending", "B")   # keep 方 pending
        rD = rec(sp3, task_b, hb_w2, "rejected", "D")  # (task_b,sp3) 冲突 → rejected 顶掉 pending，胜者归 w1
        rE = rec(sp2, task_c, hb_w2, "pending", "E")   # (task_c,sp2) 无冲突 → moved
        db.commit()

        # —— 5. 领取：keep 已领 (task_a,w1)；remove 冲突 (task_a,w2) + 可迁移 (task_c,w2) ——
        db.add(TaskClaim(task_id=task_a.id, word_id=hb_w1.id, speaker_id=sp1.id, claimed_at=now))
        db.add(TaskClaim(task_id=task_a.id, word_id=hb_w2.id, speaker_id=sp2.id, claimed_at=now))
        db.add(TaskClaim(task_id=task_c.id, word_id=hb_w2.id, speaker_id=sp2.id, claimed_at=now))
        db.commit()

        def rec_file(r):
            return Path(settings.MEDIA_ROOT) / r.audio_url.removeprefix("/media/")

        check("种子：5 录音 + 5 文件落盘",
              all(rec_file(x).is_file() for x in [rA, rB, rC, rD, rE]),
              f"ids={[x.id for x in [rA, rB, rC, rD, rE]]}")

        # ================= 查重 =================
        r = c.get("/api/words/check-duplicate", headers=SUPER,
                  params={"content": hb_w1.content})
        check("查重：精确命中 → duplicate=true 且返回 w1",
              r.status_code == 200 and r.json()["duplicate"] is True
              and r.json()["word"]["id"] == hb_w1.id,
              r.text[:80])
        r = c.get("/api/words/check-duplicate", headers=SUPER,
                  params={"content": hb_w1.content, "exclude_word_id": hb_w1.id})
        check("查重：排除自身 → duplicate=false",
              r.status_code == 200 and r.json()["duplicate"] is False, r.text[:80])
        r = c.get("/api/words/check-duplicate", headers=SUPER, params={"content": ""})
        check("查重：空 content → duplicate=false",
              r.status_code == 200 and r.json()["duplicate"] is False, r.text[:80])
        r = c.get("/api/words/check-duplicate", headers=SUPER,
                  params={"content": "不存在的内容词条xyz"})
        check("查重：未命中 → duplicate=false",
              r.status_code == 200 and r.json()["duplicate"] is False, r.text[:80])
        r = c.get("/api/words/check-duplicate", headers=SUPER, params={"content": hb_w1.content})
        check("查重：命中返回方言点", r.json()["word"]["dialect_point"] == "测试点", r.text[:80])

        # ================= merge 非法输入 =================
        r = c.post("/api/words/merge", headers=SUPER,
                   json={"keep_word_id": hb_w1.id, "remove_word_id": hb_w1.id})
        check("merge 同一词条 → 400", r.status_code == 400, str(r.status_code))
        r = c.post("/api/words/merge", headers=SUPER,
                   json={"keep_word_id": 999999, "remove_word_id": hb_w2.id})
        check("merge 词条不存在 → 404", r.status_code == 404, str(r.status_code))
        r = c.post("/api/words/merge", headers=BJ,
                   json={"keep_word_id": hb_w1.id, "remove_word_id": bj_w1.id})
        check("省管 merge 越省 → 403", r.status_code == 403, str(r.status_code))
        r = c.post("/api/words/merge", headers=BJ,
                   json={"keep_word_id": bj_w1.id, "remove_word_id": hb_w2.id})
        check("省管 merge 触碰河北词 → 403", r.status_code == 403, str(r.status_code))
        r = c.post("/api/words/merge",
                   json={"keep_word_id": hb_w1.id, "remove_word_id": hb_w2.id})
        check("merge 未登录 → 401", r.status_code == 401, str(r.status_code))

        # ================= 正式合并 =================
        r = c.post("/api/words/merge", headers=SUPER,
                   json={"keep_word_id": hb_w1.id, "remove_word_id": hb_w2.id})
        m = r.json()
        check("merge → 200", r.status_code == 200, str(r.status_code) + " " + r.text[:100])
        check("merge 计数：moved_rec=1 / removed_rec=2",
              m["moved_recordings"] == 1 and m["removed_recordings"] == 2,
              f"{m}")
        check("merge 计数：moved_claims=1 / removed_claims=1",
              m["moved_claims"] == 1 and m["removed_claims"] == 1, f"{m}")
        check("merge 计数：moved_items=2 / removed_items=1",
              m["moved_items"] == 2 and m["removed_items"] == 1, f"{m}")

        # —— 引用迁移结果 ——
        check("合并后 remove 词条消失",
              db.query(WordLibrary.id).filter(WordLibrary.id == hb_w2.id).scalar() is None)
        rec_ids = {x[0] for x in db.query(Recording.id).filter(Recording.word_id == hb_w1.id).all()}
        check("w1 名下录音 = rA + rD + rE（3 条）",
              rec_ids == {rA.id, rD.id, rE.id}, f"{sorted(rec_ids)}")
        check("w2 名下录音清零",
              db.query(Recording.id).filter(Recording.word_id == hb_w2.id).first() is None)
        check("冲突胜者 rD 已归到 w1",
              db.query(Recording.word_id).filter(Recording.id == rD.id).scalar() == hb_w1.id,
              f"{db.query(Recording.word_id).filter(Recording.id == rD.id).scalar()}")
        claim_ids = {x[0] for x in db.query(TaskClaim.id).filter(TaskClaim.word_id == hb_w1.id).all()}
        check("w1 名下领取 = keep + c_move（2 条）", len(claim_ids) == 2,
              f"{sorted(claim_ids)}")
        check("w2 名下领取清零",
              db.query(TaskClaim.id).filter(TaskClaim.word_id == hb_w2.id).first() is None)
        item_rows = db.query(TaskBatchItem.task_batch_id).filter(TaskBatchItem.word_id == hb_w1.id).all()
        check("w1 名下条目 = task_a + task_b + task_c（冲突的 task_a/w2 删除，b/c 迁移到 w1）",
              sorted(x[0] for x in item_rows) == sorted([task_a.id, task_b.id, task_c.id]),
              f"{sorted(x[0] for x in item_rows)}")
        check("w2 名下条目清零",
              db.query(TaskBatchItem.id).filter(TaskBatchItem.word_id == hb_w2.id).first() is None)

        # —— 存储文件清理 ——
        check("淘汰者 rC / rB 文件已删",
              not rec_file(rC).is_file() and not rec_file(rB).is_file(),
              f"rC={rec_file(rC).is_file()} rB={rec_file(rB).is_file()}")
        check("胜者 rD / 迁移 rE 文件保留",
              rec_file(rD).is_file() and rec_file(rE).is_file())

        # —— 合并后再对已删词条操作 → 404 ——
        r = c.post("/api/words/merge", headers=SUPER,
                   json={"keep_word_id": hb_w1.id, "remove_word_id": hb_w2.id})
        check("merge 已删词条 → 404", r.status_code == 404, str(r.status_code))

        # ================= 词条批量操作（后台完善 6）=================
        # 词条：3 个干净（可启停/可删）+ 1 个有录音（删除被拦）+ 1 个省管专用（隔离，不参与后续）
        bt_w1 = WordLibrary(code="VFY-WM-BT1", dialect_point="测试点", content="批量词一",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        bt_w2 = WordLibrary(code="VFY-WM-BT2", dialect_point="测试点", content="批量词二",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        bt_w3 = WordLibrary(code="VFY-WM-BT3", dialect_point="测试点", content="批量词三",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        bt_rec_w = WordLibrary(code="VFY-WM-BT4", dialect_point="测试点", content="批量有录音词",
                               example_sentence="测试。", province_code=HB_PROV, status="active")
        bt_prov = WordLibrary(code="VFY-WM-BT5", dialect_point="测试点", content="批量省管专用词",
                              example_sentence="测试。", province_code=HB_PROV, status="active")
        db.add_all([bt_w1, bt_w2, bt_w3, bt_rec_w, bt_prov])
        db.commit()
        rec(sp1, task_a, bt_rec_w, "pending", "BT")  # 造一条录音，让 bt_rec_w 有录音
        db.commit()

        hb_admin = AdminUser(username="verify_wm_hb", password_hash=hash_password("admin123"),
                             name="词条批量省管", role="province_admin", province_code=HB_PROV)
        db.add(hb_admin)
        db.commit()
        HB = {"Authorization": "Bearer " + create_access_token({"admin_id": hb_admin.id})}
        last_before = db.query(AdminOperationLog.id).order_by(AdminOperationLog.id.desc()).first()
        before_log_id = last_before[0] if last_before else 0

        # —— 省管批量：只处理河北，跳过北京（bt_prov 隔离使用，不干扰后续状态）——
        r = c.post("/api/words/batch-status", headers=HB,
                   json={"word_ids": [bt_prov.id, bj_w1.id], "status": "disabled"})
        j = r.json()
        check("批量禁用：省管只处理本省（河北 processed=1，北京 skipped=1）",
              r.status_code == 200 and j["processed"] == 1 and j["skipped"] == 1, r.text[:100])
        check("批量禁用：被跳过的北京词仍为 active",
              db.query(WordLibrary.status).filter(WordLibrary.id == bj_w1.id).scalar() == "active")

        # —— 批量启用/禁用语义 ——
        r = c.post("/api/words/batch-status", headers=SUPER,
                   json={"word_ids": [bt_w1.id, bt_w2.id, bt_w3.id], "status": "disabled"})
        j = r.json()
        check("批量禁用 3 词 → processed=3 / skipped=0",
              r.status_code == 200 and j["processed"] == 3 and j["skipped"] == 0, r.text[:100])
        r = c.post("/api/words/batch-status", headers=SUPER,
                   json={"word_ids": [bt_w1.id, bt_w2.id, bt_w3.id], "status": "disabled"})
        check("批量禁用：再禁用一次 → 全已禁用 → 400", r.status_code == 400, str(r.status_code))
        r = c.post("/api/words/batch-status", headers=SUPER,
                   json={"word_ids": [bt_w1.id, bt_w2.id], "status": "active"})
        j = r.json()
        check("批量启用 w1/w2 → processed=2 / skipped=0",
              r.status_code == 200 and j["processed"] == 2 and j["skipped"] == 0, r.text[:100])
        r = c.post("/api/words/batch-status", headers=SUPER,
                   json={"word_ids": [bt_w1.id, bt_w2.id, bt_w3.id], "status": "active"})
        j = r.json()
        check("批量启用 w1/w2/w3 → w1/w2 已启用跳过、只启 w3 → processed=1 / skipped=2",
              r.status_code == 200 and j["processed"] == 1 and j["skipped"] == 2, r.text[:100])
        r = c.post("/api/words/batch-status", headers=SUPER,
                   json={"word_ids": [bt_w1.id, bt_w1.id, bt_w2.id, bt_w2.id], "status": "disabled"})
        j = r.json()
        check("重复 id 去重 → 只处理不重复的（processed=2 / skipped=0）",
              r.status_code == 200 and j["processed"] == 2 and j["skipped"] == 0, r.text[:100])

        # —— 非法输入 ——
        r = c.post("/api/words/batch-status", headers=SUPER,
                   json={"word_ids": [], "status": "active"})
        check("批量禁用：空列表 → 400", r.status_code == 400, str(r.status_code))
        r = c.post("/api/words/batch-status", headers=SUPER,
                   json={"word_ids": [bt_w1.id], "status": "banana"})
        check("批量禁用：非法 status → 422", r.status_code == 422, str(r.status_code))
        r = c.post("/api/words/batch-status", headers=SUPER,
                   json={"word_ids": [999999], "status": "active"})
        check("批量禁用：词条不存在 → 404", r.status_code == 404, str(r.status_code))
        r = c.post("/api/words/batch-status", json={"word_ids": [bt_w1.id], "status": "active"})
        check("批量禁用：未登录 → 401", r.status_code == 401, str(r.status_code))

        # —— 批量删除：跳过有录音的，只删干净的 ——
        r = c.post("/api/words/batch-delete", headers=SUPER,
                   json={"word_ids": [bt_w1.id, bt_w2.id, bt_w3.id, bt_rec_w.id]})
        j = r.json()
        check("批量删除：删 3 干净 + 跳 1 有录音 → processed=3 / skipped=1",
              r.status_code == 200 and j["processed"] == 3 and j["skipped"] == 1, r.text[:100])
        ids_after = {x[0] for x in db.query(WordLibrary.id).filter(
            WordLibrary.id.in_([bt_w1.id, bt_w2.id, bt_w3.id, bt_rec_w.id])).all()}
        check("批量删除：3 干净词已删，有录音词仍在", ids_after == {bt_rec_w.id}, f"{ids_after}")
        orphan_items = db.query(TaskBatchItem.id).filter(
            TaskBatchItem.word_id.in_([bt_w1.id, bt_w2.id, bt_w3.id])).count()
        orphan_claims = db.query(TaskClaim.id).filter(
            TaskClaim.word_id.in_([bt_w1.id, bt_w2.id, bt_w3.id])).count()
        check("批量删除：干净词的任务/领取引用已清（孤儿 0）",
              orphan_items == 0 and orphan_claims == 0, f"items={orphan_items} claims={orphan_claims}")
        r = c.post("/api/words/batch-delete", headers=SUPER, json={"word_ids": [bt_rec_w.id]})
        check("批量删除：全是有录音 → 全跳过 → 400 且词条仍在",
              r.status_code == 400 and db.get(WordLibrary, bt_rec_w.id) is not None, r.text[:100])
        r = c.delete(f"/api/words/{bt_rec_w.id}", headers=SUPER)
        check("单条删除：有录音词条 → 400 拦截（加固生效）",
              r.status_code == 400 and "不能删除" in r.json().get("detail", ""), r.text[:100])
        r = c.post("/api/words/batch-delete", headers=SUPER,
                   json={"word_ids": list(range(1, 502))})
        check("批量删除：超过 500 上限 → 422", r.status_code == 422, str(r.status_code))
        r = c.post("/api/words/batch-delete", headers=SUPER, json={"word_ids": []})
        check("批量删除：空列表 → 400", r.status_code == 400, str(r.status_code))
        r = c.post("/api/words/batch-delete", headers=SUPER, json={"word_ids": [999999]})
        check("批量删除：词条不存在 → 404", r.status_code == 404, str(r.status_code))
        r = c.post("/api/words/batch-delete", json={"word_ids": [bt_w1.id]})
        check("批量删除：未登录 → 401", r.status_code == 401, str(r.status_code))

        # —— 审计日志：批量操作留痕（仅本次运行的日志）——
        batch_actions = {l.action for l in db.query(AdminOperationLog)
                         .filter(AdminOperationLog.id > before_log_id)
                         .filter(AdminOperationLog.action.like("%批量%")).all()}
        check("审计：批量启用/禁用/删除各留痕",
              {"批量启用词条", "批量禁用词条", "批量删除词条"} <= batch_actions,
              f"{sorted(batch_actions)}")

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
    # 按任务清录音（连带存储文件），再删任务/条目/领取
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证词合并-%")).all():
        for rec in db.query(Recording).filter(Recording.task_id == t.id).all():
            storage.delete_object(rec.audio_url)
            db.delete(rec)
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.query(TaskClaim).filter(TaskClaim.task_id == t.id).delete()
        db.delete(t)
    for sp in db.query(Speaker).filter(Speaker.device_id.like("verify_wm%")).all():
        for rec in db.query(Recording).filter(Recording.speaker_id == sp.id).all():
            storage.delete_object(rec.audio_url)
            db.delete(rec)
        db.query(TaskClaim).filter(TaskClaim.speaker_id == sp.id).delete()
        db.delete(sp)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY-WM%")).delete()
    db.query(AdminUser).filter(AdminUser.username.in_(["verify_wm_admin", "verify_wm_hb"])).delete()
    db.commit()


if __name__ == "__main__":
    main()
