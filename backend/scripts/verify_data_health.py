"""数据完整性巡检 + 业务健康度专项验证（进程内 TestClient）。

覆盖（后台完善 7/8）：
- 数据健康权限：GET/POST 未登录 401、省管 403（superOnly）
- 孤儿扫描：9 类核心引用计数（相对基线增量 +1，容存量孤儿）；明细含造的行
- 定向修复：{category, ids} 只删该类（同行清 item_batch+item_word 双孤儿）
- 一键修复：删全部孤儿 + 孤儿录音连带清存储文件；审计「数据健康修复」留痕；重扫 total=0
- pending-count：超管=全量、省管=本省（造北京待审单验证钳制非 0）
- dashboard/health：字段齐全、磁盘真实、storage/级别按阈值、省管钳制 pending

用法: ./.venv/Scripts/python.exe scripts/verify_data_health.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.agreement import SpeakerAgreement  # noqa: E402
from app.models.audit_log import AdminOperationLog  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402
from app.services import storage  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_data_health.txt")
results = []
SENTINEL = 900000  # 测试孤儿哨兵 id（远超真实 id），修复/清理只动哨兵行
BJ_PROV = "11"
ALL_KEYS = [
    "recording_word", "recording_task", "recording_speaker",
    "item_batch", "item_word",
    "claim_task", "claim_word", "claim_speaker",
    "agreement_speaker",
]


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def scan_counts(c, headers):
    report = c.get("/api/data-health", headers=headers).json()
    return report, {cat["key"]: cat["count"] for cat in report["categories"]}


def cleanup(db):
    """删除测试数据（哨兵孤儿 + VFY-DH 标记的北京合法数据 + 省管）。无 FK 下顺序无关。"""
    db.query(Recording).filter(Recording.word_id >= SENTINEL).delete(synchronize_session=False)
    db.query(TaskBatchItem).filter(TaskBatchItem.word_id >= SENTINEL).delete(synchronize_session=False)
    db.query(TaskClaim).filter(TaskClaim.word_id >= SENTINEL).delete(synchronize_session=False)
    db.query(SpeakerAgreement).filter(SpeakerAgreement.speaker_id >= SENTINEL).delete(synchronize_session=False)
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("VFY-DH-%")).all():
        for rec in db.query(Recording).filter(Recording.task_id == t.id).all():
            storage.delete_object(rec.audio_url)
            db.delete(rec)
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    for w in db.query(WordLibrary).filter(WordLibrary.code.like("VFY-DH-%")).all():
        db.query(Recording).filter(Recording.word_id == w.id).delete(synchronize_session=False)
        db.delete(w)
    for sp in db.query(Speaker).filter(Speaker.nickname == "VFY-DH发音人").all():
        db.query(Recording).filter(Recording.speaker_id == sp.id).delete(synchronize_session=False)
        db.delete(sp)
    db.query(AdminUser).filter(AdminUser.username == "verify_dh_bj").delete(synchronize_session=False)
    db.commit()


def main():
    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    try:
        # —— 0. 登录超管 + 建省管理员（北京）——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("超管登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}
        bj_admin = AdminUser(username="verify_dh_bj", password_hash=hash_password("admin123"),
                             name="数据健康省管", role="province_admin", province_code=BJ_PROV)
        db.add(bj_admin)
        db.commit()
        BJ = {"Authorization": "Bearer " + create_access_token({"admin_id": bj_admin.id})}

        # —— 1. 权限：未登录 401、省管 403 ——
        check("数据健康未登录 401", c.get("/api/data-health").status_code == 401)
        check("数据健康省管 403", c.get("/api/data-health", headers=BJ).status_code == 403)
        check("修复未登录 401", c.post("/api/data-health/repair").status_code == 401)
        check("修复省管 403", c.post("/api/data-health/repair", headers=BJ).status_code == 403)

        # —— 2. 基线扫描（容存量孤儿，后续用增量断言）——
        _, base = scan_counts(c, SUPER)
        check("基线返回 9 类", set(base) == set(ALL_KEYS), str(len(base)))

        # —— 3. 造孤儿（哨兵 id）：1 录音 + 1 条目 + 1 领取 + 1 协议记录，覆盖全部 9 类 ——
        rec = Recording(task_id=SENTINEL, word_id=SENTINEL, speaker_id=SENTINEL,
                        audio_url="placeholder.wav", audio_duration=100, file_size=8, status="pending")
        db.add(rec)
        db.flush()
        rec.audio_url = f"/media/verify_dh_{rec.id}.wav"
        item = TaskBatchItem(task_batch_id=SENTINEL, word_id=SENTINEL)
        db.add(item)
        claim = TaskClaim(task_id=SENTINEL, word_id=SENTINEL, speaker_id=SENTINEL)
        db.add(claim)
        agreement = SpeakerAgreement(speaker_id=SENTINEL, type="user_agreement", version=1)
        db.add(agreement)
        db.commit()
        storage.put_object(rec.audio_url, b"RIFF\x00\x00\x00\x00WAVE-verify-dh")
        disk_file = Path(settings.MEDIA_ROOT) / rec.audio_url.removeprefix("/media/")

        report, counts = scan_counts(c, SUPER)
        for k in ALL_KEYS:
            check(f"扫描 {k} 增量 +1", counts[k] == base[k] + 1, f"{counts[k]} vs {base[k]}+1")
        rec_items = next(cat["items"] for cat in report["categories"] if cat["key"] == "recording_word")
        check("录音孤儿明细可见", any(i["id"] == rec.id for i in rec_items))
        if not storage.enabled():
            check("孤儿音频文件已落盘", disk_file.exists())

        # —— 4. 定向修复 {category: item_batch}：只删造的条目（同行清 item_batch+item_word）——
        before_log = db.query(func.max(AdminOperationLog.id)).scalar() or 0
        r = c.post("/api/data-health/repair", json={"category": "item_batch", "ids": [item.id]}, headers=SUPER)
        check("定向修复 200", r.status_code == 200, str(r.status_code))
        rep = r.json()
        check("定向修复 deleted.item_batch=1", rep["deleted"].get("item_batch") == 1, str(rep))
        _, counts = scan_counts(c, SUPER)
        check("定向后 item_batch 回基线", counts["item_batch"] == base["item_batch"], str(counts["item_batch"]))
        check("定向后 item_word 回基线（同行删除）", counts["item_word"] == base["item_word"])
        check("定向后 recording_word 仍 +1", counts["recording_word"] == base["recording_word"] + 1)

        # —— 5. 一键修复（无 body=全部）：清所有孤儿 + 孤儿录音音频文件 + 审计 ——
        r = c.post("/api/data-health/repair", json={}, headers=SUPER)
        check("一键修复 200", r.status_code == 200, str(r.status_code))
        rep = r.json()
        check("一键修复 total ≥ 5（3 行造 + 存量）", rep["total"] >= 5, str(rep["total"]))
        report, counts = scan_counts(c, SUPER)
        check("修复后重扫 total=0", report["total"] == 0, str(report["total"]))
        check("修复后全部类别归 0", all(counts[k] == 0 for k in ALL_KEYS), str(counts))
        if not storage.enabled():
            check("孤儿录音音频文件已清理", not disk_file.exists())
        logs = (db.query(AdminOperationLog)
                .filter(AdminOperationLog.id > before_log,
                        AdminOperationLog.action == "数据健康修复",
                        AdminOperationLog.target_type == "system")
                .all())
        check("审计留痕 ≥2（定向+一键）", len(logs) >= 2, str(len(logs)))

        # —— 6. pending-count：超管=全量、省管=本省（造北京待审单保证非 0）——
        bj_sp = Speaker(device_id="vfy-dh-device", nickname="VFY-DH发音人", province_code=BJ_PROV)
        db.add(bj_sp)
        db.flush()
        bj_word = WordLibrary(code="VFY-DH-BJ1", dialect_point="测试点", content="数据健康北京词",
                              province_code=BJ_PROV, status="active")
        db.add(bj_word)
        db.flush()
        bj_task = TaskBatch(name="VFY-DH-任务", province_code=BJ_PROV, required_audio_count=30,
                            claim_limit=10, status="published", created_by=1)
        db.add(bj_task)
        db.flush()
        db.add(TaskBatchItem(task_batch_id=bj_task.id, word_id=bj_word.id))
        bj_rec = Recording(task_id=bj_task.id, word_id=bj_word.id, speaker_id=bj_sp.id,
                           audio_url="placeholder.wav", status="pending")
        db.add(bj_rec)
        db.flush()
        bj_rec.audio_url = f"/media/verify_dh_bj_{bj_rec.id}.wav"
        db.commit()

        def direct_pending(province=None):
            q = (db.query(func.count(Recording.id))
                 .join(TaskBatch, Recording.task_id == TaskBatch.id)
                 .filter(Recording.status == "pending"))
            if province:
                q = q.filter(TaskBatch.province_code == province)
            return q.scalar() or 0

        direct_super = direct_pending()
        direct_bj = direct_pending(BJ_PROV)
        pc_super = c.get("/api/review/pending-count", headers=SUPER).json()["pending"]
        pc_bj = c.get("/api/review/pending-count", headers=BJ).json()["pending"]
        check("pending-count 超管=全量", pc_super == direct_super, f"{pc_super} vs {direct_super}")
        check("pending-count 省管=本省", pc_bj == direct_bj, f"{pc_bj} vs {direct_bj}")
        check("pending-count 省管非 0（钳制生效）", pc_bj >= 1, str(pc_bj))

        # —— 7. dashboard/health：字段齐全 + 磁盘真实 + 级别按阈值 + 省管钳制 ——
        h = c.get("/api/dashboard/health", headers=SUPER).json()
        need = ["pending", "today_uploaded", "today_approved", "today_rejected",
                "disk_total_gb", "disk_used_gb", "disk_free_gb", "disk_used_pct",
                "storage", "backlog_level", "disk_level"]
        check("health 字段齐全", all(k in h for k in need), str(list(h)))
        check("health pending=全量", h["pending"] == direct_super, f"{h['pending']} vs {direct_super}")
        check("health 磁盘真实", h["disk_total_gb"] > 0 and h["disk_used_gb"] > 0, f"total={h['disk_total_gb']}G")
        check("health storage 合法", h["storage"] in ("cos", "local"), h["storage"])
        exp_backlog = "high" if direct_super >= settings.BACKLOG_WARN_PENDING else "normal"
        check("health backlog_level 按阈值", h["backlog_level"] == exp_backlog, h["backlog_level"])
        free_pct = h["disk_free_gb"] / h["disk_total_gb"] * 100 if h["disk_total_gb"] else 100.0
        exp_disk = "warn" if free_pct < settings.DISK_WARN_FREE_PCT else "ok"
        check("health disk_level 按阈值", h["disk_level"] == exp_disk, h["disk_level"])
        h_bj = c.get("/api/dashboard/health", headers=BJ).json()
        check("health 省管 pending=本省", h_bj["pending"] == direct_bj, f"{h_bj['pending']} vs {direct_bj}")

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
