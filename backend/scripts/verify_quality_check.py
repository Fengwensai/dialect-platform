"""录音质量预检专项验证（进程内 TestClient，纯标准库生成 WAV）。

覆盖：
- 上传自动检测：0.5s 全零 → suspect(too_short+silent)；2s 正常音量正弦 → ok；
  2s 过轻正弦 → suspect(too_quiet)；非 WAV(mp3 魔数) → unparsed
- duration 用服务端计算的 WAV 时长，不信任客户端字段（传 duration=1000 仍判 too_short）
- 审核列表 quality 过滤：quality=suspect/ok/unparsed 各只返回对应类；非法值 422
- 审核列表透出 quality_status/quality_flags/quality_metrics 字段

用法: ./.venv/Scripts/python.exe scripts/verify_quality_check.py
"""
import io
import math
import os
import struct
import sys
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402
from app.models.team_code import TeamCode  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402
from app.services import storage  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_quality_check.txt")
results = []
DEVICE = "verify_qual"
TEAM = "VFYQ-01"  # 11/1101 北京，无真实团队码不冲突
PROV, CITY = "11", "1101"


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def make_wav(duration_s, amplitude, sample_rate=16000):
    """生成 16kHz 单声道 16bit PCM WAV 字节（内存）。"""
    n = int(duration_s * sample_rate)
    frames = bytearray()
    for i in range(n):
        s = 0 if amplitude == 0 else int(
            amplitude * 32767 * math.sin(2 * math.pi * 440 * i / sample_rate)
        )
        frames += struct.pack("<h", s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def cleanup(db):
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证质量-%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskClaim).filter(TaskClaim.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    for sp in db.query(Speaker).filter(Speaker.device_id.like("verify_qual%")).all():
        db.query(Recording).filter(Recording.speaker_id == sp.id).delete()
        db.query(TaskClaim).filter(TaskClaim.speaker_id == sp.id).delete()
        db.delete(sp)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFYQ-%")).delete()
    db.query(TeamCode).filter(TeamCode.code == TEAM).delete()
    db.commit()


def main():
    # 阈值固定为默认值，避免本地 .env 自定义阈值导致断言漂移
    settings.QUALITY_MIN_DURATION_MS = 800
    settings.QUALITY_SILENCE_RATIO = 0.9
    settings.QUALITY_MIN_RMS_DB = -40.0

    # 上传落盘改走内存，避免测试文件污染本地 media 目录（质量检测发生在落盘前，不受影响）
    _store = {}
    storage.put_object = lambda path, content: _store.__setitem__(path, content)  # noqa: E731

    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    try:
        # —— 0. 管理端登录 ——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("管理端登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}

        # —— 1. 建团队码 / 4 词条 / 任务发布 ——
        r = c.post("/api/team-codes", headers=SUPER,
                   json={"code": TEAM, "name": "验证质量团队", "province_code": PROV, "city_code": CITY})
        check("建团队码 VFYQ-01", r.status_code == 200, str(r.status_code) + " " + str(r.json()))
        words = []
        for i in range(4):
            w = WordLibrary(code=f"VFYQ-W{i+1}", dialect_point="北京话", content=f"质量预检词{i+1}",
                            example_sentence="测试。", province_code=PROV, status="active")
            db.add(w)
            db.flush()
            words.append(w)
        db.commit()
        r = c.post("/api/tasks", headers=SUPER, json={
            "name": "验证质量任务", "description": "质量预检验证",
            "province_code": PROV, "city_code": CITY, "team_code": TEAM,
            "required_audio_count": 30, "word_ids": [w.id for w in words]})
        task_id = r.json().get("id") if r.status_code == 200 else None
        check("建任务", r.status_code == 200 and task_id, str(r.status_code) + " " + str(r.json()))
        r = c.post(f"/api/tasks/{task_id}/publish", headers=SUPER)
        check("发布任务", r.status_code == 200 and r.json().get("status") == "published",
              str(r.status_code) + " " + str(r.json()))

        # —— 2. 发音人：直写 + 直签 token + 协议 + 绑团队 + 领取 ——
        sp = Speaker(device_id=DEVICE, nickname="质量验证发音人")
        db.add(sp)
        db.flush()
        sp_id = sp.id
        db.commit()
        SP = {"Authorization": "Bearer " + create_access_token(
            {"speaker_id": sp_id, "openid": "", "role": "speaker"})}
        r = c.get("/api/mp/agreements")
        ag = r.json() if r.status_code == 200 else []
        r = c.post("/api/mp/agreements/accept", headers=SP,
                   json={"accepted": [{"type": a["type"], "version": a["version"]} for a in ag]})
        check("同意协议", r.status_code == 200, str(r.status_code) + " " + str(r.json()))
        r = c.post("/api/mp/team/join", headers=SP, json={"code": TEAM})
        check("绑定团队", r.status_code == 200 and r.json().get("province_code") == PROV,
              str(r.status_code) + " " + str(r.json()))
        r = c.post(f"/api/mp/tasks/{task_id}/claims", headers=SP,
                   json={"word_ids": [w.id for w in words]})
        check("领取 4 词条", r.status_code == 200
              and len(r.json().get("claimed_word_ids", [])) == 4,
              str(r.status_code) + " " + str(r.json()))

        # —— 3. 上传四份（静音短 / 正常 / 过轻 / 非WAV），每份落不同词条 ——
        def upload(word, wav_bytes, ext, duration_ms):
            data = {"task_id": str(task_id), "word_id": str(word.id),
                    "duration": str(duration_ms), "device_id": DEVICE}
            r = c.post("/api/mp/recordings", headers=SP, data=data,
                       files={"file": (f"q{ext}", wav_bytes, "audio/wav")})
            rid = r.json().get("recording_id") if r.status_code == 200 else None
            return rid, r

        rid_short, r = upload(words[0], make_wav(0.5, 0.0), ".wav", 1000)
        rec_short = db.get(Recording, rid_short) if rid_short else None
        check("上传静音短录音", r.status_code == 200 and rid_short,
              str(r.status_code) + " " + str(r.json()))
        check("0.5s 全零 → suspect + too_short + silent",
              rec_short is not None and rec_short.quality_status == "suspect"
              and "too_short" in (rec_short.quality_flags or "")
              and "silent" in (rec_short.quality_flags or ""),
              f"status={rec_short.quality_status if rec_short else None} "
              f"flags={rec_short.quality_flags if rec_short else None}")
        check("duration 用服务端计算值(500ms) 而非客户端 1000ms",
              rec_short is not None and rec_short.quality_metrics.get("duration_ms") == 500,
              str(rec_short.quality_metrics if rec_short else None))

        rid_ok, r = upload(words[1], make_wav(2.0, 0.3), ".wav", 2000)
        rec_ok = db.get(Recording, rid_ok) if rid_ok else None
        check("上传正常录音", r.status_code == 200 and rid_ok, str(r.status_code) + " " + str(r.json()))
        check("2s 正常音量 → ok 无旗标",
              rec_ok is not None and rec_ok.quality_status == "ok"
              and not (rec_ok.quality_flags or ""),
              f"status={rec_ok.quality_status if rec_ok else None} "
              f"flags={rec_ok.quality_flags if rec_ok else None}")

        rid_quiet, r = upload(words[2], make_wav(2.0, 0.001), ".wav", 2000)
        rec_quiet = db.get(Recording, rid_quiet) if rid_quiet else None
        check("上传过轻录音", r.status_code == 200 and rid_quiet, str(r.status_code) + " " + str(r.json()))
        check("2s 过轻 → suspect + too_quiet",
              rec_quiet is not None and rec_quiet.quality_status == "suspect"
              and "too_quiet" in (rec_quiet.quality_flags or ""),
              f"status={rec_quiet.quality_status if rec_quiet else None} "
              f"flags={rec_quiet.quality_flags if rec_quiet else None}")

        # 非 WAV：合法扩展名 + 非 RIFF 魔数 → unparsed
        rid_np, r = upload(words[3], b"ID3\x03\x00" + b"\x00" * 64, ".mp3", 1000)
        rec_np = db.get(Recording, rid_np) if rid_np else None
        check("上传非 WAV(mp3 魔数)", r.status_code == 200 and rid_np,
              str(r.status_code) + " " + str(r.json()))
        check("非 WAV → unparsed 无旗标",
              rec_np is not None and rec_np.quality_status == "unparsed"
              and not (rec_np.quality_flags or ""),
              f"status={rec_np.quality_status if rec_np else None}")

        # —— 4. 审核列表 quality 过滤 + 字段透出 ——
        r = c.get("/api/review/recordings", headers=SUPER, params={"quality": "suspect"})
        ids = {x["id"] for x in r.json().get("items", [])}
        check("quality=suspect → 只返回 2 条 suspect",
              r.status_code == 200 and r.json()["total"] == 2 and ids == {rid_short, rid_quiet},
              f"total={r.json().get('total')} ids={sorted(ids)}")
        r = c.get("/api/review/recordings", headers=SUPER, params={"quality": "ok"})
        ids = {x["id"] for x in r.json().get("items", [])}
        check("quality=ok → 只返回 ok", r.status_code == 200 and ids == {rid_ok}, f"{sorted(ids)}")
        r = c.get("/api/review/recordings", headers=SUPER, params={"quality": "unparsed"})
        ids = {x["id"] for x in r.json().get("items", [])}
        check("quality=unparsed → 只返回 unparsed", r.status_code == 200 and ids == {rid_np},
              f"{sorted(ids)}")
        r = c.get("/api/review/recordings", headers=SUPER, params={"quality": "bad"})
        check("非法 quality → 422", r.status_code == 422, str(r.status_code))
        r = c.get("/api/review/recordings", headers=SUPER, params={"quality": "ok"})
        item_ok = next((x for x in r.json().get("items", []) if x["id"] == rid_ok), None)
        check("列表字段透出 quality_status/flags/metrics",
              item_ok is not None and item_ok["quality_status"] == "ok"
              and item_ok["quality_flags"] is None and isinstance(item_ok["quality_metrics"], dict),
              str(item_ok))

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
