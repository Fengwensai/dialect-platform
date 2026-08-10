"""COS 模式端到端验证（进程内 fake client，无需真实腾讯云凭据）。

用 storage.set_client_override(FakeCosClient) 注入内存对象存储 + FastAPI TestClient，
验证服务器中转上传、重录删旧、预签名播放 URL、ZIP 导出、内容安全预签名 media_url。
HTTP 回归脚本跑在独立服务进程，monkeypatch 够不着，故 COS 路径必须进程内验证。

依赖：cos-python-sdk-v5（qcloud_cos）、httpx（fastapi.testclient）。
用法: ./.venv/Scripts/python.exe scripts/verify_cos_mode.py
"""
import csv
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from qcloud_cos import CosServiceError  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.team_code import TeamCode  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402
from app.services import content_security as cs  # noqa: E402
from app.services import storage  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_cos_mode.txt")
results = []
DEVICE = "verify_cos"
TEAM = "VFY0-COS"  # 11/1101 北京，无真实团队码不冲突
PROV, CITY = "11", "1101"


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


class _FakeBody:
    def __init__(self, data: bytes):
        self._b = io.BytesIO(data)

    def get_raw_stream(self):
        return self._b

    def read(self):
        return self._b.read()

    def close(self):
        self._b.close()


class FakeCosClient:
    """内存对象存储：put/get/delete/get_presigned_url，签名 URL 用固定格式。"""

    def __init__(self):
        self._store = {}

    def put_object(self, Bucket, Key, Body=None, **kw):
        self._store[Key] = bytes(Body) if not isinstance(Body, bytes) else Body
        return {"ETag": "fake"}

    def get_object(self, Bucket, Key, **kw):
        if Key not in self._store:
            raise CosServiceError(
                {"response": {"error": {"code": "NoSuchKey", "message": ""}}}, {}, 404
            )
        return {"Body": _FakeBody(self._store[Key])}

    def delete_object(self, Bucket, Key, **kw):
        self._store.pop(Key, None)
        return {}

    def get_presigned_url(self, Method="GET", Bucket=None, Key=None, Expired=300, **kw):
        return f"https://{Bucket}.cos.example.com/{Key}?q-sign-expires={Expired}"


def make_wav(seconds=1, rate=16000):
    import struct

    data = b"\x00\x00" * (rate * seconds)
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return header + fmt + b"data" + struct.pack("<I", len(data)) + data


def cleanup(db):
    for sp in db.query(Speaker).filter(Speaker.device_id == DEVICE).all():
        db.query(Recording).filter(Recording.speaker_id == sp.id).delete()
        db.execute(text("DELETE FROM speaker_agreements WHERE speaker_id = :sid"), {"sid": sp.id})
        db.delete(sp)
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证COS%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY0-%")).delete()
    db.query(TeamCode).filter(TeamCode.code.like("VFY0-%")).delete()
    db.commit()


def main():
    # —— 0. 进入 COS 模式：dummy 凭据使 enabled()=True + 注入 fake client ——
    old = {k: getattr(settings, k) for k in
           ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_REGION", "COS_BUCKET")}
    settings.COS_SECRET_ID = "testid"
    settings.COS_SECRET_KEY = "testkey"
    settings.COS_REGION = "ap-guangzhou"
    settings.COS_BUCKET = "fakebucket-1250000000"
    storage.set_client_override(FakeCosClient())
    check("COS 模式启用（四项凭据齐全）", storage.enabled() and storage.get_client() is not None)

    # 内容安全：全程用 fake，避免触真实微信网络；记录每次传入的 media_url
    captured = {"media_url": None, "openid": None}

    def fake_check(openid, media_url):
        captured["media_url"] = media_url
        captured["openid"] = openid
        return "trace_cos_1"

    cs.check_media_async = fake_check

    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    try:
        # —— 1. 管理端登录 ——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("管理端登录", r.status_code == 200, str(r.status_code))
        SUPER = r.json()["access_token"]

        # —— 2. 建团队码 / 词条 / 任务发布 ——
        r = c.post("/api/team-codes", headers={"Authorization": f"Bearer {SUPER}"},
                   json={"code": TEAM, "name": "验证COS团队", "province_code": PROV,
                         "city_code": CITY})
        check("建团队码 VFY0-COS", r.status_code == 200, str(r.status_code) + " " + str(r.json()))
        w1 = WordLibrary(code="VFY0-C1", dialect_point="北京话", content="COS词条一",
                         example_sentence="测试。", province_code=PROV, status="active")
        w2 = WordLibrary(code="VFY0-C2", dialect_point="北京话", content="COS词条二",
                         example_sentence="测试。", province_code=PROV, status="active")
        db.add(w1)
        db.add(w2)
        db.flush()
        db.commit()
        r = c.post("/api/tasks", headers={"Authorization": f"Bearer {SUPER}"}, json={
            "name": "验证COS任务", "description": "COS模式验证",
            "province_code": PROV, "city_code": CITY, "team_code": TEAM,
            "required_audio_count": 30, "word_ids": [w1.id, w2.id]})
        task_id = r.json().get("id") if r.status_code == 200 else None
        check("建任务", r.status_code == 200 and task_id, str(r.status_code) + " " + str(r.json()))
        r = c.post(f"/api/tasks/{task_id}/publish", headers={"Authorization": f"Bearer {SUPER}"})
        check("发布任务", r.status_code == 200 and r.json().get("status") == "published",
              str(r.status_code) + " " + str(r.json()))

        # —— 3. 发音人：直写 + 直签 token + 协议 + 绑团队 ——
        sp = Speaker(device_id=DEVICE, nickname="COS验证发音人")
        db.add(sp)
        db.flush()
        sp_id = sp.id
        db.commit()
        SP = {"Authorization": "Bearer " + create_access_token(
            {"speaker_id": sp_id, "openid": "", "role": "speaker"})}
        r = c.get("/api/mp/agreements")
        ag = r.json() if r.status_code == 200 else []
        body = {"accepted": [{"type": a["type"], "version": a["version"]} for a in ag]}
        r = c.post("/api/mp/agreements/accept", headers=SP, json=body)
        check("同意协议", r.status_code == 200, str(r.status_code) + " " + str(r.json()))
        r = c.post("/api/mp/team/join", headers=SP, json={"code": TEAM})
        check("绑定团队", r.status_code == 200 and r.json().get("province_code") == PROV,
              str(r.status_code) + " " + str(r.json()))

        # —— 4. 上传 wav：fake store 落 key，返回逻辑路径 ——
        wav = make_wav()
        files = {"file": ("vfy.wav", wav, "audio/wav")}
        data = {"task_id": str(task_id), "word_id": str(w1.id), "duration": "1000",
                "device_id": DEVICE}
        r = c.post("/api/mp/recordings", headers=SP, data=data, files=files)
        key1 = f"recordings/{task_id}/{task_id}_{w1.id}_{sp_id}.wav"
        fake = storage.get_client()
        check("上传 wav → COS 落 key", r.status_code == 200
              and fake._store.get(key1) == wav and r.json().get("audio_url") == f"/media/{key1}",
              str(r.status_code) + " " + str(r.json()))

        # —— 5. 同词条换扩展名重录：旧 wav key 删除，新 mp3 key 落 ——
        mp3bytes = b"ID3" + wav  # 内容不必真 mp3，仅验证存储 key 语义
        files = {"file": ("vfy.mp3", mp3bytes, "audio/mpeg")}
        r = c.post("/api/mp/recordings", headers=SP, data=data, files=files)
        key_mp3 = f"recordings/{task_id}/{task_id}_{w1.id}_{sp_id}.mp3"
        check("重录换扩展名 → 旧 key 删、新 key 落", r.status_code == 200
              and key1 not in fake._store and fake._store.get(key_mp3) == mp3bytes,
              str(r.status_code) + " " + str(r.json()))

        # —— 6. 同 key 重录：覆盖不产生孤儿 ——
        r = c.post("/api/mp/recordings", headers=SP, data=data, files=files)
        check("同 key 重录覆盖", r.status_code == 200 and fake._store.get(key_mp3) == mp3bytes
              and r.json().get("overwritten") is True, str(r.json()))

        # —— 7. 上传 w2（供审核/导出）——
        data2 = dict(data, word_id=str(w2.id))
        r = c.post("/api/mp/recordings", headers=SP, data=data2, files={"file": ("vfy.wav", wav, "audio/wav")})
        rec2 = r.json().get("recording_id") if r.status_code == 200 else None
        check("上传 w2 录音", r.status_code == 200 and rec2, str(r.status_code) + " " + str(r.json()))

        # —— 8. 审核列表：audio_url 为 COS 预签名 URL ——
        r = c.get("/api/review/recordings", headers={"Authorization": f"Bearer {SUPER}"},
                  params={"task_id": task_id})
        items = r.json().get("items", [])
        signed = [i["audio_url"] for i in items if i["id"] == rec2]
        check("审核列表 audio_url 为预签名", r.status_code == 200 and len(items) == 2
              and signed and signed[0].startswith("https://fakebucket-1250000000.cos.example.com/")
              and "q-sign-expires=3600" in signed[0],
              str(signed[0])[:90] if signed else str(r.json()))

        # —— 9. 审核通过 rec2 + 导出 ZIP 内容一致 ——
        r = c.post(f"/api/review/recordings/{rec2}/verdict",
                   headers={"Authorization": f"Bearer {SUPER}"},
                   json={"approved": True, "note": ""})
        check("审核通过 rec2", r.status_code == 200 and r.json().get("status") == "approved",
              str(r.status_code) + " " + str(r.json()))
        r = c.get("/api/review/export", headers={"Authorization": f"Bearer {SUPER}"},
                  params={"task_id": task_id})
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/zip"):
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            audio_names = [n for n in zf.namelist() if n.startswith("audios/")]
            manifest = zf.read("manifest.csv").decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(manifest)))
            ok = (len(audio_names) == 1 and zf.read(audio_names[0]) == wav
                  and len(rows) == 1 and rows[0]["audio_present"] == "1")
            check("导出 ZIP 音频内容一致", ok, f"audio={audio_names} rows={len(rows)}")
        else:
            check("导出 ZIP 音频内容一致", False, str(r.status_code) + " " + str(r.text[:120]))

        # —— 10. 内容安全：fire_media_check 传的是预签名 media_url，状态回写 ——
        rec = db.get(Recording, rec2)
        before = rec.content_check_status
        cs.fire_media_check(rec2)
        db.refresh(rec)
        check("内容安全 media_url 为预签名", captured["media_url"] is not None
              and captured["media_url"].startswith("https://fakebucket-1250000000.cos.example.com/")
              and "q-sign-expires=3600" in captured["media_url"],
              str(captured["media_url"])[:90])
        check("content_check_status 回写 media_pending",
              rec.content_check_status == "media_pending",
              f"{before} → {rec.content_check_status}")

        cleanup(db)
    finally:
        storage.clear_client_override()
        for k, v in old.items():
            setattr(settings, k, v)
        db.close()

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    passed = sum(1 for x in results if x.startswith("[PASS]"))
    failed = sum(1 for x in results if x.startswith("[FAIL]"))
    print(f"RESULT: {passed} PASS / {failed} FAIL (详见 {OUT})")


if __name__ == "__main__":
    main()
