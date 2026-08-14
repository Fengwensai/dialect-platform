"""演示任务（is_demo）端到端验证（进程内 TestClient，无需独立服务进程）。

覆盖微信审核员冷启动场景：
- 未绑定团队的发音人：能看演示任务、能看词条、能上传录音；看不到/传不了地区真实任务。
- 已绑定团队的发音人：看不到演示任务，demo 任务词条 403、上传 403；正常看到本地区任务。
前置：先跑 scripts/migrate_demo_tasks.py（本机 PG 需有 is_demo 列）。
依赖：httpx（fastapi.testclient）。
用法: ./.venv/Scripts/python.exe scripts/verify_demo_task.py
"""
import io
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_demo_task.txt")
results = []
DEV_U, DEV_B = "verify_demo_u", "verify_demo_b"
DEMO_PROV, DEMO_CITY = "11", "1101"  # 演示任务投放区划（未绑定用户不按地区过滤）
REAL_PROV, REAL_CITY = "13", "1301"  # 真实任务投放区划（河北石家庄）


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def make_wav(seconds=1, rate=16000):
    data = b"\x00\x00" * (rate * seconds)
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return header + fmt + b"data" + struct.pack("<I", len(data)) + data


def accept_all(c, headers, db):
    """同意全部协议（require_agreements_accepted 依赖要求）。"""
    r = c.get("/api/mp/agreements", headers=headers)
    ag = r.json() if r.status_code == 200 else []
    body = {"accepted": [{"type": a["type"], "version": a["version"]} for a in ag]}
    r = c.post("/api/mp/agreements/accept", headers=headers, json=body)
    return r.status_code == 200


def sign_speaker(db, device_id, province=None, city=None, team=None):
    sp = Speaker(device_id=device_id, nickname="演示验证发音人")
    if province:
        sp.province_code = province
        sp.city_code = city
        sp.team_code = team
    db.add(sp)
    db.flush()
    db.commit()
    return sp, {"Authorization": "Bearer " + create_access_token(
        {"speaker_id": sp.id, "openid": "", "role": "speaker"})}


def cleanup(db):
    for dev in (DEV_U, DEV_B):
        for sp in db.query(Speaker).filter(Speaker.device_id == dev).all():
            db.query(Recording).filter(Recording.speaker_id == sp.id).delete()
            db.query(TaskClaim).filter(TaskClaim.speaker_id == sp.id).delete()
            db.execute(text("DELETE FROM speaker_agreements WHERE speaker_id = :sid"),
                       {"sid": sp.id})
            db.delete(sp)
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证演示%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskClaim).filter(TaskClaim.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY-D%")).delete()
    db.commit()


def main():
    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    try:
        # —— 0. 管理端登录 ——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("管理端登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}

        # —— 1. 建词条 + 演示任务 + 真实任务（均发布） ——
        w1 = WordLibrary(code="VFY-D1", dialect_point="北京话", content="演示词条一",
                         example_sentence="测试。", province_code=DEMO_PROV, status="active")
        w2 = WordLibrary(code="VFY-D2", dialect_point="北京话", content="演示词条二",
                         example_sentence="测试。", province_code=DEMO_PROV, status="active")
        db.add(w1)
        db.add(w2)
        db.flush()
        db.commit()
        r = c.post("/api/tasks", headers=SUPER, json={
            "name": "验证演示任务", "description": "审核体验用",
            "province_code": DEMO_PROV, "city_code": DEMO_CITY, "team_code": None,
            "required_audio_count": 2, "word_ids": [w1.id, w2.id], "is_demo": True})
        demo_id = r.json().get("id") if r.status_code == 200 else None
        check("建演示任务(is_demo)", r.status_code == 200 and demo_id,
              str(r.status_code) + " " + str(r.json()))
        c.post(f"/api/tasks/{demo_id}/publish", headers=SUPER)
        r = c.post("/api/tasks", headers=SUPER, json={
            "name": "验证演示-真实任务", "description": "真实地区任务",
            "province_code": REAL_PROV, "city_code": REAL_CITY, "team_code": None,
            "required_audio_count": 2, "word_ids": [w2.id], "is_demo": False})
        real_id = r.json().get("id") if r.status_code == 200 else None
        check("建真实任务", r.status_code == 200 and real_id, str(r.status_code))
        c.post(f"/api/tasks/{real_id}/publish", headers=SUPER)

        # —— 2. 发音人：未绑定 + 已绑定（河北石家庄），均同意协议 ——
        sp_u, U = sign_speaker(db, DEV_U)
        sp_b, B = sign_speaker(db, DEV_B, province=REAL_PROV, city=REAL_CITY,
                               team="HB-SJZ")
        check("未绑定/已绑定发音人同意协议", accept_all(c, U, db) and accept_all(c, B, db))

        # —— 3. 未绑定：只能看到演示任务 ——
        r = c.get("/api/mp/tasks", headers=U)
        items = r.json().get("items", [])
        ids = [i["id"] for i in items]
        demo_item = next((i for i in items if i["id"] == demo_id), None)
        check("未绑定→只看到演示任务", r.status_code == 200 and demo_id in ids
              and real_id not in ids and demo_item and demo_item.get("is_demo") is True,
              f"ids={ids}")

        # —— 3.5 领取制：未绑定先领取演示任务 w1/w2（/words 现在只返回已领）——
        r = c.post(f"/api/mp/tasks/{demo_id}/claims", headers=U,
                   json={"word_ids": [w1.id, w2.id]})
        check("未绑定→领取演示任务 2 词条", r.status_code == 200
              and len(r.json().get("claimed_word_ids", [])) == 2,
              str(r.status_code) + " " + str(r.json()))

        # —— 4. 未绑定：演示任务词条可见 ——
        r = c.get(f"/api/mp/tasks/{demo_id}/words", headers=U)
        check("未绑定→演示任务词条可见", r.status_code == 200 and r.json().get("total") == 2,
              str(r.status_code) + " " + str(r.json().get("total")))

        # —— 5. 未绑定：上传到演示任务成功 ——
        wav = make_wav()
        r = c.post("/api/mp/recordings", headers=U, data={
            "task_id": str(demo_id), "word_id": str(w1.id), "duration": "1000",
            "device_id": DEV_U},
            files={"file": ("vfy.wav", wav, "audio/wav")})
        check("未绑定→上传演示任务成功", r.status_code == 200
              and r.json().get("status") == "pending", str(r.status_code) + " " + str(r.json()))

        # —— 6. 未绑定：上传真实地区任务被拒（属地门禁） ——
        r = c.post("/api/mp/recordings", headers=U, data={
            "task_id": str(real_id), "word_id": str(w2.id), "duration": "1000",
            "device_id": DEV_U},
            files={"file": ("vfy.wav", wav, "audio/wav")})
        check("未绑定→上传真实任务被拒(400)", r.status_code == 400,
              str(r.status_code) + " " + r.text[:80])

        # —— 7. 已绑定：看不到演示任务 ——
        r = c.get("/api/mp/tasks", headers=B)
        items = r.json().get("items", [])
        ids = [i["id"] for i in items]
        real_item = next((i for i in items if i["id"] == real_id), None)
        check("已绑定→看不到演示任务", r.status_code == 200 and real_id in ids
              and demo_id not in ids and real_item and real_item.get("is_demo") is False,
              f"ids={ids}")

        # —— 8. 已绑定：演示任务词条/上传均 403 ——
        r = c.get(f"/api/mp/tasks/{demo_id}/words", headers=B)
        check("已绑定→演示词条 403", r.status_code == 403, str(r.status_code))
        r = c.post("/api/mp/recordings", headers=B, data={
            "task_id": str(demo_id), "word_id": str(w1.id), "duration": "1000",
            "device_id": DEV_B},
            files={"file": ("vfy.wav", wav, "audio/wav")})
        check("已绑定→上传演示任务 403", r.status_code == 403, str(r.status_code))

        cleanup(db)
    finally:
        db.close()

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    passed = sum(1 for x in results if x.startswith("[PASS]"))
    failed = sum(1 for x in results if x.startswith("[FAIL]"))
    print(f"RESULT: {passed} PASS / {failed} FAIL (详见 {OUT})")


if __name__ == "__main__":
    main()
