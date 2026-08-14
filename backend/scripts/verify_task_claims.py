"""领取制专项验证（进程内 TestClient，无需独立服务进程）。

覆盖领取制核心语义（全部确定性断言）：
- 未领取上传 403「未被你领取」（守卫在限流之前）
- 领取词条归我专有 → /words 只返回已领、任务列表 my_claimed 计数
- 他人已领词条：抢领 409、上传 403
- count 模式只领可领数（不越池）
- 自退：未录可退、已录 400
- 管理端解绑：未录可解绑、已录 400
- claim_limit 上限封顶
- 并发 10 人抢 5 词条 → 恰好 5×200 + 5×409（行锁串行，池只减不增）

依赖：httpx（fastapi.testclient）。
用法: ./.venv/Scripts/python.exe scripts/verify_task_claims.py
"""
import os
import struct
import sys
from concurrent.futures import ThreadPoolExecutor

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
from app.models.team_code import TeamCode  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_task_claims.txt")
results = []
TEAM = "VFY0-CLM"  # 11/1101 北京
PROV, CITY = "11", "1101"


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


def sign_speaker(db, device_id, nickname="领取验证发音人"):
    sp = Speaker(device_id=device_id, nickname=nickname)
    db.add(sp)
    db.flush()
    db.commit()
    return sp, {"Authorization": "Bearer " + create_access_token(
        {"speaker_id": sp.id, "openid": "", "role": "speaker"})}


def cleanup(db):
    for sp in db.query(Speaker).filter(Speaker.device_id.like("verify_claim%")).all():
        db.query(Recording).filter(Recording.speaker_id == sp.id).delete()
        db.query(TaskClaim).filter(TaskClaim.speaker_id == sp.id).delete()
        db.execute(text("DELETE FROM speaker_agreements WHERE speaker_id = :sid"), {"sid": sp.id})
        db.delete(sp)
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证领取%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskClaim).filter(TaskClaim.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY-C%")).delete()
    db.query(TeamCode).filter(TeamCode.code == TEAM).delete()
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

        # —— 1. 建团队码 + 词条 w1..w5 ——
        r = c.post("/api/team-codes", headers=SUPER,
                   json={"code": TEAM, "name": "验证领取团队", "province_code": PROV, "city_code": CITY})
        check("建团队码 VFY0-CLM", r.status_code == 200, str(r.status_code) + " " + str(r.json()))
        words = []
        for i in range(1, 9):
            w = WordLibrary(code=f"VFY-C{i}", dialect_point="北京话", content=f"领取验证词条{i}",
                            example_sentence="测试。", province_code=PROV, status="active")
            db.add(w)
            db.flush()
            words.append(w)
        db.commit()
        w1, w2, w3, w4, w5, w6, w7, w8 = words
        check("直写词条 8 条", all(w.id for w in words), f"ids={[w.id for w in words]}")

        # —— 2. 任务 A（claim_limit=10，池 3）+ 任务 B（claim_limit=2，池 5），均发布 ——
        def make_task(name, ids, limit):
            r = c.post("/api/tasks", headers=SUPER, json={
                "name": name, "province_code": PROV, "city_code": CITY,
                "team_code": TEAM, "required_audio_count": 30,
                "word_ids": ids, "claim_limit": limit})
            tid = r.json().get("id") if r.status_code == 200 else None
            c.post(f"/api/tasks/{tid}/publish", headers=SUPER)
            return tid

        ta = make_task("验证领取任务", [w1.id, w2.id, w3.id], 10)
        tb = make_task("验证领取-上限", [w4.id, w5.id, w6.id, w7.id, w8.id], 2)
        check("建任务 A/B 并发布", bool(ta and tb), f"ta={ta} tb={tb}")

        # —— 3. 发音人：sp_a / sp_b / sp_x + 并发 10 人，均绑团队 + 同意协议 ——
        def make_bound(device, nickname):
            sp, H = sign_speaker(db, device, nickname)
            if not accept_all(c, H):
                return None
            r = c.post("/api/mp/team/join", headers=H, json={"code": TEAM})
            if r.status_code != 200:
                return None
            return sp, H

        sp_a, HA = make_bound("verify_claim_a", "领取甲")
        sp_b, HB = make_bound("verify_claim_b", "领取乙")
        sp_x, HX = make_bound("verify_claim_x", "领取上限验证")
        conc = [make_bound(f"verify_claim_c{i:02d}", f"并发{i:02d}") for i in range(1, 11)]
        check("发音人全部绑定团队", all(p is not None for p in [sp_a, sp_b, sp_x] + conc),
              f"a={bool(sp_a)} b={bool(sp_b)} x={bool(sp_x)} conc={sum(p is not None for p in conc)}/10")

        # —— 4. 未领取上传 403（守卫在限流之前，不消耗配额）——
        wav = make_wav()
        r = c.post("/api/mp/recordings", headers=HA, data={
            "task_id": str(ta), "word_id": str(w1.id), "duration": "1000",
            "device_id": "verify_claim_a"},
            files={"file": ("vfy.wav", wav, "audio/wav")})
        check("未领取上传 403 未被你领取", r.status_code == 403 and "未被你领取" in str(r.json()),
              str(r.status_code) + " " + r.text[:80])

        # —— 5. 领取 [w1,w2] → 归我专有；/words 只返回已领 ——
        r = c.post(f"/api/mp/tasks/{ta}/claims", headers=HA, json={"word_ids": [w1.id, w2.id]})
        body = r.json()
        check("领取 2 词条归我专有", r.status_code == 200
              and len(body.get("claimed_word_ids", [])) == 2
              and body["stats"]["my_claimed"] == 2 and body["stats"]["available"] == 1,
              str(r.status_code) + " " + str(body))
        r = c.get(f"/api/mp/tasks/{ta}/words", headers=HA)
        wr = r.json()
        check("任务 A /words 只返回已领 2 条", r.status_code == 200
              and wr.get("total") == 2 and wr["claim"]["my_claimed"] == 2,
              f"total={wr.get('total')} ids={[w['word_id'] for w in wr.get('items', [])]}")
        r = c.get("/api/mp/tasks", headers=HA)
        item = next((i for i in r.json().get("items", []) if i["id"] == ta), None)
        check("任务列表 my_claimed=2 可领=1", item is not None
              and item.get("my_claimed") == 2 and item.get("claimable") == 1,
              f"my_claimed={item and item.get('my_claimed')} claimable={item and item.get('claimable')}")

        # —— 6. 他人已领词条：抢领 409、上传 403 ——
        r = c.post(f"/api/mp/tasks/{ta}/claims", headers=HB, json={"word_ids": [w1.id]})
        check("第二人抢领已领词条 409", r.status_code == 409, str(r.status_code) + " " + r.text[:80])
        r = c.post("/api/mp/recordings", headers=HB, data={
            "task_id": str(ta), "word_id": str(w1.id), "duration": "1000",
            "device_id": "verify_claim_b"},
            files={"file": ("vfy.wav", wav, "audio/wav")})
        check("第二人上传他人已领词条 403", r.status_code == 403 and "未被你领取" in str(r.json()),
              str(r.status_code) + " " + r.text[:80])

        # —— 7. count 模式只领可领（池剩余 1，不越池）——
        r = c.post(f"/api/mp/tasks/{ta}/claims", headers=HB, json={"count": 10})
        body = r.json()
        check("count 模式只领可领 1 条", r.status_code == 200
              and len(body.get("claimed_word_ids", [])) == 1
              and body["stats"]["my_claimed"] == 1 and w3.id in body.get("claimed_word_ids", []),
              str(r.status_code) + " " + str(body))

        # —— 8. 自退：未录可退；已录不可退 400 ——
        r = c.delete(f"/api/mp/tasks/{ta}/claims/{w3.id}", headers=HB)
        body = r.json()
        check("自退未录词条成功", r.status_code == 200 and body.get("my_claimed") == 0
              and body.get("available") == 1, str(r.status_code) + " " + str(body))
        r = c.post("/api/mp/recordings", headers=HA, data={
            "task_id": str(ta), "word_id": str(w1.id), "duration": "1000",
            "device_id": "verify_claim_a"},
            files={"file": ("vfy.wav", wav, "audio/wav")})
        check("sp_a 上传已领 w1 成功", r.status_code == 200, str(r.status_code) + " " + str(r.json()))
        r = c.delete(f"/api/mp/tasks/{ta}/claims/{w1.id}", headers=HA)
        check("已录词条不可自退 400", r.status_code == 400 and "已录制" in str(r.json()),
              str(r.status_code) + " " + r.text[:80])

        # —— 9. 管理端解绑：未录可解绑、已录 400 ——
        r = c.get(f"/api/tasks/{ta}/claims", headers=SUPER)
        cl = r.json()
        cw1 = next((x for x in cl if x["word_id"] == w1.id), None)
        cw2 = next((x for x in cl if x["word_id"] == w2.id), None)
        check("后台领取列表 w1(已录)/w2(未录)", r.status_code == 200 and cw1 and cw2
              and cw1["recorded"] is True and cw2["recorded"] is False,
              f"w1.recorded={cw1 and cw1['recorded']} w2.recorded={cw2 and cw2['recorded']}")
        r = c.delete(f"/api/tasks/{ta}/claims/{cw2['claim_id']}", headers=SUPER)
        check("管理端解绑未录词条", r.status_code == 200, str(r.status_code) + " " + str(r.json()))
        r = c.delete(f"/api/tasks/{ta}/claims/{cw1['claim_id']}", headers=SUPER)
        check("管理端解绑已录词条 400", r.status_code == 400 and "已录制" in str(r.json()),
              str(r.status_code) + " " + r.text[:80])

        # —— 10. claim_limit 上限封顶（任务 B：limit=2、池 5）——
        r = c.post(f"/api/mp/tasks/{tb}/claims", headers=HX, json={"count": 10})
        body = r.json()
        check("claim_limit=2 → 最多领 2 条", r.status_code == 200
              and len(body.get("claimed_word_ids", [])) == 2
              and body["stats"]["my_claimed"] == 2,
              str(r.status_code) + " " + str(body))
        r = c.post(f"/api/mp/tasks/{tb}/claims", headers=HX, json={"count": 1})
        check("已达上限再领 409", r.status_code == 409, str(r.status_code) + " " + r.text[:80])
        for wid in body.get("claimed_word_ids", []):
            c.delete(f"/api/mp/tasks/{tb}/claims/{wid}", headers=HX)
        r = c.get(f"/api/mp/tasks/{tb}/claims", headers=HX)
        check("自退后任务 B 池回满", r.status_code == 200 and r.json().get("available") == 5,
              str(r.json().get("available")))

        # —— 11. 并发 10 人抢任务 B 5 词条：恰好 5×200 + 5×409 ——
        def claim_one(pair):
            _, H = pair
            client = TestClient(app)
            r = client.post(f"/api/mp/tasks/{tb}/claims", headers=H, json={"count": 1})
            return r.status_code

        with ThreadPoolExecutor(max_workers=10) as ex:
            codes = list(ex.map(claim_one, conc))
        n200 = codes.count(200)
        n409 = codes.count(409)
        check("并发 10 人抢 5 词条 → 5×200 + 5×409", n200 == 5 and n409 == 5 and len(codes) == 10,
              f"codes={sorted(codes)}")

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
