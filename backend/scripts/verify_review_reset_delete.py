"""审核闭环专项验证：驳回重置为待审 + 单条删除（仅已驳回）（进程内 TestClient）。

覆盖：
- 重置 rejected → pending：note/reviewed_by/reviewed_at 清空、转写保留
- 重置 pending/approved → 400；不存在 → 404；省管越省 → 403
- 删除 rejected → DB 行消失 + 本地音频文件删除（真实落盘验证）
- 删除 pending/approved → 400；不存在 → 404；省管越省 → 403

用法: ./.venv/Scripts/python.exe scripts/verify_review_reset_delete.py
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
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402
from app.services import storage  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_review_reset_delete.txt")
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
        hb_admin = AdminUser(username="verify_rst_admin", password_hash=hash_password("admin123"),
                             name="重置删除省管", role="province_admin", province_code=HB_PROV)
        db.add(hb_admin)
        db.commit()
        HB = {"Authorization": "Bearer " + create_access_token({"admin_id": hb_admin.id})}

        # —— 1. 词条 + 任务（河北 + 北京）——
        hb_w1 = WordLibrary(code="VFY-RS-HB1", dialect_point="测试点", content="重置删除河北词1",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        hb_w2 = WordLibrary(code="VFY-RS-HB2", dialect_point="测试点", content="重置删除河北词2",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        bj_w1 = WordLibrary(code="VFY-RS-BJ1", dialect_point="测试点", content="重置删除北京词1",
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

        task_hb = make_task("验证重置-河北", HB_PROV, [hb_w1, hb_w2])
        task_bj = make_task("验证重置-北京", BJ_PROV, [bj_w1])
        db.commit()

        # —— 2. 发音人 ——
        def make_sp(dev, nick, prov):
            sp = Speaker(device_id=dev, nickname=nick, province_code=prov,
                         gender="male", age_bracket="age18_30", openid="vrs_" + dev)
            db.add(sp)
            db.flush()
            return sp

        sp_hb1 = make_sp("verify_rst_hb1", "重置河北甲", HB_PROV)
        sp_hb2 = make_sp("verify_rst_hb2", "重置河北乙", HB_PROV)
        sp_bj = make_sp("verify_rst_bj1", "重置北京", BJ_PROV)

        # —— 3. 录音 5 条（真实落盘音频，供删除清理验证）——
        def rec(sp, t, w, status, extra=None):
            audio_url = f"/media/recordings/{t.id}/{t.id}_{w.id}_{sp.id}.wav"
            storage.put_object(audio_url, b"verify-reset-delete")
            d = dict(task_id=t.id, word_id=w.id, speaker_id=sp.id, audio_url=audio_url,
                     audio_duration=1000, file_size=21, status=status, created_at=now)
            d.update(extra or {})
            r = Recording(**d)
            db.add(r)
            db.flush()
            return r

        r1 = rec(sp_hb1, task_hb, hb_w1, "rejected", extra={
            "review_note": "口音不标准", "reviewed_by": 1, "reviewed_at": now,
            "mandarin_transcript": "测试普通话", "dialect_transcript": "ts/ts/"})
        r2 = rec(sp_hb1, task_hb, hb_w2, "pending")
        r3 = rec(sp_hb2, task_hb, hb_w1, "approved", extra={"reviewed_by": 1, "reviewed_at": now})
        r4 = rec(sp_bj, task_bj, bj_w1, "rejected", extra={"reviewed_by": 1, "reviewed_at": now})
        r5 = rec(sp_hb2, task_hb, hb_w2, "rejected",
                 extra={"review_note": "噪音大", "reviewed_by": 1, "reviewed_at": now})
        db.commit()

        def rec_file(r):
            return Path(settings.MEDIA_ROOT) / r.audio_url.removeprefix("/media/")

        check("种子：5 录音 + 5 文件落盘",
              all(x.id for x in [r1, r2, r3, r4, r5])
              and all(rec_file(x).is_file() for x in [r1, r2, r3, r4, r5]))

        # ================= 重置 =================
        r = c.post(f"/api/review/recordings/{r1.id}/reset", headers=SUPER)
        db.refresh(r1)
        check("重置 rejected → pending", r.status_code == 200 and r.json()["status"] == "pending",
              str(r.status_code) + " " + r.text[:80])
        check("重置清空判决痕迹（note/审核人/时间）",
              r1.review_note is None and r1.reviewed_by is None and r1.reviewed_at is None,
              f"note={r1.review_note}")
        check("重置保留转写",
              r1.mandarin_transcript == "测试普通话" and r1.dialect_transcript == "ts/ts/",
              f"{r1.mandarin_transcript} / {r1.dialect_transcript}")

        r = c.post(f"/api/review/recordings/{r1.id}/reset", headers=SUPER)
        check("已重置为 pending 再重置 → 400", r.status_code == 400 and "仅已驳回" in str(r.json()),
              str(r.status_code))
        r = c.post(f"/api/review/recordings/{r2.id}/reset", headers=SUPER)
        check("pending 重置 → 400", r.status_code == 400, str(r.status_code))
        r = c.post(f"/api/review/recordings/{r3.id}/reset", headers=SUPER)
        check("approved 重置 → 400", r.status_code == 400, str(r.status_code))
        r = c.post("/api/review/recordings/999999/reset", headers=SUPER)
        check("重置不存在 → 404", r.status_code == 404, str(r.status_code))
        r = c.post(f"/api/review/recordings/{r4.id}/reset", headers=HB)
        check("省管重置越省 → 403", r.status_code == 403, str(r.status_code))

        # ================= 删除 =================
        r = c.delete(f"/api/review/recordings/{r5.id}", headers=SUPER)
        check("删除 rejected → 200", r.status_code == 200, str(r.status_code) + " " + r.text[:80])
        # 直接发 SQL 查 id 是否存在（不用 db.get：identity map 里缓存的 r5 对象会干扰）
        check("删除后 DB 行消失", db.query(Recording.id).filter(Recording.id == r5.id).scalar() is None)
        check("删除后本地音频文件已清理", not rec_file(r5).is_file())

        r = c.delete(f"/api/review/recordings/{r2.id}", headers=SUPER)
        check("删除 pending → 400", r.status_code == 400 and "仅已驳回" in str(r.json()), str(r.status_code))
        r = c.delete(f"/api/review/recordings/{r3.id}", headers=SUPER)
        check("删除 approved → 400", r.status_code == 400, str(r.status_code))
        r = c.delete(f"/api/review/recordings/{r1.id}", headers=SUPER)
        check("删除已重置(pending) → 400", r.status_code == 400, str(r.status_code))
        r = c.delete("/api/review/recordings/999999", headers=SUPER)
        check("删除不存在 → 404", r.status_code == 404, str(r.status_code))
        r = c.delete(f"/api/review/recordings/{r4.id}", headers=HB)
        check("省管删除越省 → 403", r.status_code == 403, str(r.status_code))

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
    # 删任务下录音（DB + 本地文件）再删任务，随后删发音人/词条/省管
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证重置-%")).all():
        for rec in db.query(Recording).filter(Recording.task_id == t.id).all():
            storage.delete_object(rec.audio_url)
            db.delete(rec)
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    for sp in db.query(Speaker).filter(Speaker.device_id.like("verify_rst%")).all():
        for rec in db.query(Recording).filter(Recording.speaker_id == sp.id).all():
            storage.delete_object(rec.audio_url)
            db.delete(rec)
        db.delete(sp)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY-RS%")).delete()
    db.query(AdminUser).filter(AdminUser.username == "verify_rst_admin").delete()
    db.commit()


if __name__ == "__main__":
    main()
