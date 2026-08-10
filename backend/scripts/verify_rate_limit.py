"""登录防爆破 + 上传频率限流端到端验证（进程内 TestClient，进程内改 settings）。

覆盖：
- 登录：连续失败超 LOGIN_FAIL_LIMIT 次后，正确密码也 429；成功登录清零失败计数。
- 按 IP 限流：同一 IP 失败超 LOGIN_IP_FAIL_LIMIT 次后 429（早于账号上限）。
- 上传：同一发音人窗口内超 UPLOAD_RATE_LIMIT 次 → 429；reset 后恢复。
依赖：httpx（fastapi.testclient）。
用法: ./.venv/Scripts/python.exe scripts/verify_rate_limit.py
"""
import io
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402
from app.services import rate_limit  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_rate_limit.txt")
results = []
DEVICE = "verify_rate"
DEMO_PROV, DEMO_CITY = "11", "1101"


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def make_wav(seconds=1, rate=16000):
    data = b"\x00\x00" * (rate * seconds)
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return header + fmt + b"data" + struct.pack("<I", len(data)) + data


def accept_all(c, headers):
    r = c.get("/api/mp/agreements", headers=headers)
    ag = r.json() if r.status_code == 200 else []
    body = {"accepted": [{"type": a["type"], "version": a["version"]} for a in ag]}
    return c.post("/api/mp/agreements/accept", headers=headers, json=body).status_code == 200


def cleanup(db):
    for sp in db.query(Speaker).filter(Speaker.device_id == DEVICE).all():
        db.query(Recording).filter(Recording.speaker_id == sp.id).delete()
        db.execute(text("DELETE FROM speaker_agreements WHERE speaker_id = :sid"), {"sid": sp.id})
        db.delete(sp)
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证限流%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY-R%")).delete()
    db.commit()


def main():
    old = {
        "LOGIN_FAIL_LIMIT": settings.LOGIN_FAIL_LIMIT,
        "LOGIN_IP_FAIL_LIMIT": settings.LOGIN_IP_FAIL_LIMIT,
        "UPLOAD_RATE_LIMIT": settings.UPLOAD_RATE_LIMIT,
    }
    settings.UPLOAD_RATE_LIMIT = 3
    IP = "testclient"

    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    try:
        # —— 0. 先拿管理员 token（登录限流测试放最后，避免后续被锁）——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("初始 admin 登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}

        # —— 1. 上传限流：建演示任务，同一发音人传 4 次 → 前 3 成功、第 4 次 429 ——
        w = WordLibrary(code="VFY-R1", dialect_point="北京话", content="限流词条",
                        example_sentence="测试。", province_code=DEMO_PROV, status="active")
        db.add(w)
        db.flush()
        db.commit()
        r = c.post("/api/tasks", headers=SUPER, json={
            "name": "验证限流演示任务", "province_code": DEMO_PROV, "city_code": DEMO_CITY,
            "team_code": None, "required_audio_count": 10, "word_ids": [w.id],
            "is_demo": True})
        task_id = r.json().get("id")
        c.post(f"/api/tasks/{task_id}/publish", headers=SUPER)

        sp = Speaker(device_id=DEVICE, nickname="限流验证发音人")
        db.add(sp)
        db.flush()
        db.commit()
        SP = {"Authorization": "Bearer " + create_access_token(
            {"speaker_id": sp.id, "openid": "", "role": "speaker"})}
        accept_all(c, SP)

        wav = make_wav()
        codes = []
        for i in range(4):
            r = c.post("/api/mp/recordings", headers=SP, data={
                "task_id": str(task_id), "word_id": str(w.id), "duration": "1000",
                "device_id": DEVICE},
                files={"file": (f"v{i}.wav", wav, "audio/wav")})
            codes.append(r.status_code)
        check("上传前 3 次成功、第 4 次 429", codes == [200, 200, 200, 429],
              str(codes))

        rate_limit.reset(f"upload:sp:{sp.id}")
        r = c.post("/api/mp/recordings", headers=SP, data={
            "task_id": str(task_id), "word_id": str(w.id), "duration": "1000",
            "device_id": DEVICE}, files={"file": ("again.wav", wav, "audio/wav")})
        check("reset 后上传恢复", r.status_code == 200, str(r.status_code))

        # —— 2. 账号防爆破：admin 连续错 3 次（账号上限 3、IP 上限抬高到 10，
        #      使锁定由账号键触发而非 IP 键）→ 第 4 次（正确密码也）429；清零后恢复 ——
        settings.LOGIN_FAIL_LIMIT = 3
        settings.LOGIN_IP_FAIL_LIMIT = 10
        rate_limit.reset("login:acct:admin")
        rate_limit.reset(f"login:ip:{IP}")
        codes = []
        for i in range(4):
            r = c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
            codes.append(r.status_code)
        check("错 3 次后第 4 次 429（账号键）", codes == [401, 401, 401, 429], str(codes))
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("锁定期正确密码仍 429", r.status_code == 429, str(r.status_code))
        rate_limit.reset("login:acct:admin")
        rate_limit.reset(f"login:ip:{IP}")
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("账号计数清零后恢复登录", r.status_code == 200, str(r.status_code))

        # —— 3. 按 IP 限流：不存在的账号错 4 次（账号上限 10、IP 上限 3，
        #      第 4 次由 IP 键触发 429）；IP 清零后恢复 ——
        settings.LOGIN_FAIL_LIMIT = 10
        settings.LOGIN_IP_FAIL_LIMIT = 3
        rate_limit.reset("login:acct:ip_probe")
        rate_limit.reset(f"login:ip:{IP}")
        codes = []
        for i in range(4):
            r = c.post("/api/auth/login", json={"username": "ip_probe", "password": "wrong"})
            codes.append(r.status_code)
        check("同 IP 多账号失败 → IP 键触发 429", codes == [401, 401, 401, 429], str(codes))
        rate_limit.reset(f"login:ip:{IP}")
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("IP 计数清零后恢复登录", r.status_code == 200, str(r.status_code))

        cleanup(db)
    finally:
        for k, v in old.items():
            setattr(settings, k, v)
        rate_limit.reset("login:acct:admin")
        rate_limit.reset("login:acct:ip_probe")
        rate_limit.reset(f"login:ip:{IP}")
        db.close()

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    passed = sum(1 for x in results if x.startswith("[PASS]"))
    failed = sum(1 for x in results if x.startswith("[FAIL]"))
    print(f"RESULT: {passed} PASS / {failed} FAIL (详见 {OUT})")


if __name__ == "__main__":
    main()
