"""发音人合并专项验证（进程内 TestClient）。

覆盖：
- merge 引用迁移：Recording / TaskClaim / SpeakerAgreement 改 speaker_id
- 录音冲突去重：(task, word) 冲突按状态保留（approved>rejected>pending）+ 淘汰者存储文件删除；
  含「remove 方胜出」场景（rejected 顶掉 keep 的 pending，胜者归到 keep，不产生孤儿引用）
- claim 冲突：(task, word) keep 已领则删 remove 的
- agreement 冲突：同 type 保留 version 大者（remove 的 v2 顶掉 keep 的 v1）
- remove 的 device_id/openid 置空后安全删除（绕过唯一约束）+ 头像文件清理
- keep==remove → 400；不存在 → 404；省管越省 → 403；未登录 → 401

用法: ./.venv/Scripts/python.exe scripts/verify_speaker_merge.py
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
from app.models.agreement import SpeakerAgreement  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402
from app.services import storage  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_speaker_merge.txt")
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
        bj_admin = AdminUser(username="verify_sm_admin", password_hash=hash_password("admin123"),
                             name="发音人合并省管", role="province_admin", province_code=BJ_PROV)
        db.add(bj_admin)
        db.commit()
        BJ = {"Authorization": "Bearer " + create_access_token({"admin_id": bj_admin.id})}

        # —— 1. 词条 + 任务 ——
        def make_task(name, prov, wid):
            t = TaskBatch(name=name, province_code=prov, required_audio_count=30,
                          claim_limit=10, status="published", created_by=1)
            db.add(t)
            db.flush()
            db.add(TaskBatchItem(task_batch_id=t.id, word_id=wid))
            return t

        hb_w1 = WordLibrary(code="VFY-SM-HB1", dialect_point="测试点", content="发音人合并词1",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        hb_w2 = WordLibrary(code="VFY-SM-HB2", dialect_point="测试点", content="发音人合并词2",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        hb_w3 = WordLibrary(code="VFY-SM-HB3", dialect_point="测试点", content="发音人合并词3",
                            example_sentence="测试。", province_code=HB_PROV, status="active")
        bj_w1 = WordLibrary(code="VFY-SM-BJ1", dialect_point="测试点", content="发音人合并北京词",
                            example_sentence="测试。", province_code=BJ_PROV, status="active")
        db.add_all([hb_w1, hb_w2, hb_w3, bj_w1])
        db.flush()
        task_a = make_task("验证发音人合并-A", HB_PROV, hb_w1.id)
        task_b = make_task("验证发音人合并-B", HB_PROV, hb_w2.id)
        task_c = make_task("验证发音人合并-C", HB_PROV, hb_w3.id)
        task_bj = make_task("验证发音人合并-BJ", BJ_PROV, bj_w1.id)
        db.commit()

        # —— 2. 发音人：keep=sp_k / remove=sp_r（河北），bj_sp（北京，403 用）——
        sp_k = Speaker(device_id="verify_sm_k", nickname="发音人合并留", province_code=HB_PROV,
                       gender="male", age_bracket="age18_30", openid="vsm_k", team_code="VFY-SM-T")
        sp_r = Speaker(device_id="verify_sm_r", nickname="发音人合并去", province_code=HB_PROV,
                       gender="female", age_bracket="age31_45", openid="vsm_r")
        bj_sp = Speaker(device_id="verify_sm_bj", nickname="发音人合并北京", province_code=BJ_PROV,
                        gender="male", age_bracket="age18_30", openid="vsm_bj")
        db.add_all([sp_k, sp_r, bj_sp])
        db.flush()
        db.commit()

        # remove 带真实头像文件（合并后应被清理）
        avatar_url = "/media/avatars/verify_sm_r.png"
        avatar_path = Path(settings.MEDIA_ROOT) / "avatars" / "verify_sm_r.png"
        avatar_path.parent.mkdir(parents=True, exist_ok=True)
        avatar_path.write_bytes(b"fake-avatar")
        sp_r.avatar_url = avatar_url
        db.commit()

        # —— 3. 录音（真实落盘）——
        def rec(sp, t, w, st, label):
            audio_url = f"/media/recordings/{t.id}/{label}.wav"
            storage.put_object(audio_url, b"verify-speaker-merge")
            rr = Recording(task_id=t.id, word_id=w.id, speaker_id=sp.id, audio_url=audio_url,
                           audio_duration=1000, file_size=21, status=st,
                           content_check_status="media_passed", created_at=now)
            db.add(rr)
            db.flush()
            return rr

        rA = rec(sp_k, task_a, hb_w1, "approved", "A")  # keep 方 approved
        rC = rec(sp_r, task_a, hb_w1, "rejected", "C")  # (task_a,w1) 冲突 → rejected 输给 approved，删
        rD = rec(sp_r, task_b, hb_w2, "pending", "D")   # (task_b,w2) 无冲突 → moved
        rE = rec(sp_k, task_c, hb_w3, "pending", "E")   # keep 方 pending
        rF = rec(sp_r, task_c, hb_w3, "rejected", "F")  # (task_c,w3) 冲突 → rejected 顶掉 pending，胜者归 keep
        db.commit()

        # —— 4. 领取：keep 已领 (task_a,w1)；remove 可迁移 (task_b,w2) ——
        # 注：UNIQUE(task_id, word_id) 一词一领，故「同 (task,word) 冲突」在约束下不可达，
        # 冲突分支为防御性代码；此处仅验证引用迁移。
        db.add(TaskClaim(task_id=task_a.id, word_id=hb_w1.id, speaker_id=sp_k.id, claimed_at=now))
        db.add(TaskClaim(task_id=task_b.id, word_id=hb_w2.id, speaker_id=sp_r.id, claimed_at=now))
        db.commit()

        # —— 5. 协议：keep privacy v1；remove privacy v2 + recruit v1 ——
        db.add(SpeakerAgreement(speaker_id=sp_k.id, type="privacy", version=1, accepted_at=now))
        db.add(SpeakerAgreement(speaker_id=sp_r.id, type="privacy", version=2, accepted_at=now))
        db.add(SpeakerAgreement(speaker_id=sp_r.id, type="recruit", version=1, accepted_at=now))
        db.commit()

        def rec_file(r):
            return Path(settings.MEDIA_ROOT) / r.audio_url.removeprefix("/media/")

        check("种子：5 录音 + 5 文件落盘 + 头像文件",
              all(rec_file(x).is_file() for x in [rA, rC, rD, rE, rF]) and avatar_path.is_file(),
              f"ids={[x.id for x in [rA, rC, rD, rE, rF]]}")

        # ================= merge 非法输入 =================
        r = c.post("/api/speakers/merge", headers=SUPER,
                   json={"keep_speaker_id": sp_k.id, "remove_speaker_id": sp_k.id})
        check("merge 同一发音人 → 400", r.status_code == 400, str(r.status_code))
        r = c.post("/api/speakers/merge", headers=SUPER,
                   json={"keep_speaker_id": 999999, "remove_speaker_id": sp_r.id})
        check("merge 发音人不存在 → 404", r.status_code == 404, str(r.status_code))
        r = c.post("/api/speakers/merge", headers=BJ,
                   json={"keep_speaker_id": bj_sp.id, "remove_speaker_id": sp_r.id})
        check("省管 merge 越省 → 403", r.status_code == 403, str(r.status_code))
        r = c.post("/api/speakers/merge", headers=BJ,
                   json={"keep_speaker_id": sp_k.id, "remove_speaker_id": bj_sp.id})
        check("省管 merge 触碰河北发音人 → 403", r.status_code == 403, str(r.status_code))
        r = c.post("/api/speakers/merge",
                   json={"keep_speaker_id": sp_k.id, "remove_speaker_id": sp_r.id})
        check("merge 未登录 → 401", r.status_code == 401, str(r.status_code))

        # ================= 正式合并 =================
        r = c.post("/api/speakers/merge", headers=SUPER,
                   json={"keep_speaker_id": sp_k.id, "remove_speaker_id": sp_r.id})
        m = r.json()
        check("merge → 200", r.status_code == 200, str(r.status_code) + " " + r.text[:100])
        check("merge 计数：moved_rec=1 / removed_rec=2",
              m["moved_recordings"] == 1 and m["removed_recordings"] == 2, f"{m}")
        check("merge 计数：moved_claims=1 / removed_claims=0",
              m["moved_claims"] == 1 and m["removed_claims"] == 0, f"{m}")
        check("merge 计数：moved_agreements=1 / removed_agreements=1",
              m["moved_agreements"] == 1 and m["removed_agreements"] == 1, f"{m}")

        # —— 引用迁移结果 ——
        check("合并后 remove 发音人消失",
              db.query(Speaker.id).filter(Speaker.id == sp_r.id).scalar() is None)
        rec_ids = {x[0] for x in db.query(Recording.id).filter(Recording.speaker_id == sp_k.id).all()}
        check("keep 名下录音 = rA + rD + rF（3 条）",
              rec_ids == {rA.id, rD.id, rF.id}, f"{sorted(rec_ids)}")
        check("remove 名下录音清零",
              db.query(Recording.id).filter(Recording.speaker_id == sp_r.id).first() is None)
        check("冲突胜者 rF 已归到 keep",
              db.query(Recording.speaker_id).filter(Recording.id == rF.id).scalar() == sp_k.id,
              f"{db.query(Recording.speaker_id).filter(Recording.id == rF.id).scalar()}")
        claim_ids = {x[0] for x in db.query(TaskClaim.id).filter(TaskClaim.speaker_id == sp_k.id).all()}
        check("keep 名下领取 = c_keep + c_move（2 条）", len(claim_ids) == 2, f"{sorted(claim_ids)}")
        check("remove 名下领取清零",
              db.query(TaskClaim.id).filter(TaskClaim.speaker_id == sp_r.id).first() is None)
        ags = {a.type: a.version for a in
               db.query(SpeakerAgreement).filter(SpeakerAgreement.speaker_id == sp_k.id).all()}
        check("keep 协议 = privacy v2 + recruit v1（v2 顶掉 v1）",
              ags == {"privacy": 2, "recruit": 1}, f"{ags}")
        check("remove 名下协议清零",
              db.query(SpeakerAgreement.id).filter(SpeakerAgreement.speaker_id == sp_r.id).first() is None)

        # —— 存储/头像清理 ——
        check("淘汰者 rC / rE 文件已删",
              not rec_file(rC).is_file() and not rec_file(rE).is_file(),
              f"rC={rec_file(rC).is_file()} rE={rec_file(rE).is_file()}")
        check("胜者 rF / 迁移 rD 文件保留",
              rec_file(rF).is_file() and rec_file(rD).is_file())
        check("remove 头像文件已清理", not avatar_path.is_file())

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
    sps = db.query(Speaker).filter(Speaker.device_id.like("verify_sm%")).all()
    sp_ids = [s.id for s in sps]
    if sp_ids:
        for rec in db.query(Recording).filter(Recording.speaker_id.in_(sp_ids)).all():
            storage.delete_object(rec.audio_url)
            db.delete(rec)
        db.query(TaskClaim).filter(TaskClaim.speaker_id.in_(sp_ids)).delete()
        db.query(SpeakerAgreement).filter(SpeakerAgreement.speaker_id.in_(sp_ids)).delete()
        _av = Path(settings.MEDIA_ROOT) / "avatars" / "verify_sm_r.png"
        if _av.is_file():
            _av.unlink()
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证发音人合并-%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskClaim).filter(TaskClaim.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    for s in sps:
        db.delete(s)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY-SM%")).delete()
    db.query(AdminUser).filter(AdminUser.username == "verify_sm_admin").delete()
    db.commit()


if __name__ == "__main__":
    main()
