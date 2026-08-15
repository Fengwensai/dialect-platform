"""阶段十·上线准备端到端验证：管理端建码/建任务 → 发音人登录/同意协议/绑团队 →
领任务 → 上传录音 → 后台审核/驳回 → 导出 ZIP → 内容安全单测 → 我的时长统计/导出。

对运行中的服务 HTTP 调用验证（发音人 token 直签绕过微信登录）；内容安全为进程内
monkeypatch 确定性单测（不依赖公网）。输出 UTF-8 写文件，避免 Git Bash 控制台 GBK 乱码。
用法: ./.venv/Scripts/python.exe scripts/verify_mp_full_flow.py
"""
import csv
import io
import os
import struct
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text  # noqa: E402

import requests  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402
from app.models.team_code import TeamCode  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402
from app.services import content_security as cs  # noqa: E402

BASE = "http://127.0.0.1:8000"
OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_mp_full_flow.txt")

results = []


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def api(method, path, token=None, body=None, params=None, **kw):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    kwargs = {"params": params}
    if body is not None:
        kwargs["json"] = body
    return requests.request(method, BASE + path, headers=headers, **kwargs, timeout=15)


def j(r):
    try:
        return r.json()
    except Exception:
        return r.text[:200]


def make_wav(seconds=1, rate=16000):
    """生成合法小 WAV：RIFF + fmt + data（静音 PCM 16bit mono），约 32KB。"""
    data = b"\x00\x00" * (rate * seconds)
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return header + fmt + b"data" + struct.pack("<I", len(data)) + data


DEVICE = "verify_mp_full"
TEAM = "VFY0-FLOW"  # 11/1101 北京（该省市无真实团队码，一码一区不冲突）
PROV, CITY = "11", "1101"


def cleanup(db):
    """清理全部 VFY0- 前缀验证数据（幂等，运行前后各一次）。"""
    for sp in db.query(Speaker).filter(Speaker.device_id.like(DEVICE + "%")).all():
        db.query(Recording).filter(Recording.speaker_id == sp.id).delete()
        db.execute(text("DELETE FROM speaker_agreements WHERE speaker_id = :sid"), {"sid": sp.id})
        db.delete(sp)
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证端到端%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskClaim).filter(TaskClaim.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY0-%")).delete()
    db.query(TeamCode).filter(TeamCode.code.like("VFY0-%")).delete()
    db.commit()


def main():
    db = SessionLocal()
    cleanup(db)
    try:
        # —— 0. 管理端登录 ——
        r = api("POST", "/api/auth/login", body={"username": "admin", "password": "admin123"})
        check("管理端登录", r.status_code == 200, str(r.status_code))
        SUPER = r.json()["access_token"]

        # —— 1. 建团队码（11/1101，北京）——
        r = api("POST", "/api/team-codes", token=SUPER,
                body={"code": TEAM, "name": "验证端到端团队", "province_code": PROV, "city_code": CITY})
        check("创建团队码 VFY0-FLOW", r.status_code == 200,
              str(r.status_code) + " " + str(j(r)) if r.status_code != 200 else "")

        # —— 2. 直写词条 2 条（province=11, active）——
        w1 = WordLibrary(code="VFY0-W1", dialect_point="北京话", content="验证词条一",
                         example_sentence="今天天气真好。", province_code=PROV, status="active")
        w2 = WordLibrary(code="VFY0-W2", dialect_point="北京话", content="验证词条二",
                         example_sentence="吃了吗您。", province_code=PROV, status="active")
        db.add(w1)
        db.add(w2)
        db.flush()
        db.commit()
        check("直写词条 2 条", w1.id and w2.id, f"w1={w1.id} w2={w2.id}")

        # —— 3. 建任务（关联团队码 + 两词条）→ 发布 ——
        r = api("POST", "/api/tasks", token=SUPER, body={
            "name": "验证端到端任务", "description": "阶段十端到端验证",
            "province_code": PROV, "city_code": CITY, "team_code": TEAM,
            "required_audio_count": 30, "word_ids": [w1.id, w2.id],
        })
        task_id = j(r).get("id") if r.status_code == 200 else None
        check("创建任务关联团队带出地区", r.status_code == 200 and task_id and j(r).get("team_code") == TEAM
              and j(r).get("city_code") == CITY, str(r.status_code) + " " + str(j(r)))
        r = api("POST", f"/api/tasks/{task_id}/publish", token=SUPER)
        check("发布任务 → published", r.status_code == 200 and j(r).get("status") == "published",
              str(r.status_code) + " " + str(j(r)))

        # —— 4. 直写发音人 + 直签 token ——
        sp = Speaker(device_id=DEVICE, nickname="端到端验证发音人")
        db.add(sp)
        db.flush()
        sp_id = sp.id
        db.commit()
        sp_token = create_access_token({"speaker_id": sp_id, "openid": "", "role": "speaker"})
        SP = {"Authorization": "Bearer " + sp_token}

        # —— 5. 协议：公开拉取 → 全同意 → pending 空 ——
        r = api("GET", "/api/mp/agreements")
        ag = j(r) if r.status_code == 200 else []
        v_by_type = {a["type"]: a["version"] for a in ag}
        check("公开协议 3 类", r.status_code == 200 and len(ag) == 3, f"types={[a['type'] for a in ag]}")
        body = {"accepted": [{"type": t, "version": v} for t, v in v_by_type.items()]}
        r = api("POST", "/api/mp/agreements/accept", token=sp_token, body=body)
        check("同意全部协议", r.status_code == 200 and r.json()["pending_agreements"] == [],
              str(j(r)))
        r = api("GET", "/api/mp/agreements/pending", token=sp_token)
        check("pending 已清空", r.status_code == 200 and r.json()["pending_agreements"] == [],
              str(j(r)))

        # —— 6. 加入团队：绑定属地 11/1101 ——
        r = api("POST", "/api/mp/team/join", token=sp_token, body={"code": TEAM})
        s = j(r)
        check("绑定团队带出属地", r.status_code == 200 and s.get("province_code") == PROV
              and s.get("city_code") == CITY and s.get("team_code") == TEAM,
              str(r.status_code) + " " + str(s))

        # —— 7. 领任务：仅本地区 ——
        r = api("GET", "/api/mp/tasks", token=sp_token)
        items = j(r).get("items", [])
        check("mp_tasks 仅返回本地区任务", r.status_code == 200 and any(i["id"] == task_id for i in items)
              and all(i["province_code"] == PROV for i in items),
              f"total={j(r).get('total')}")

        # —— 7.5 领取制：领取 2 词条 → 归我专有；第二人抢领 409、未领上传 403 ——
        wav = make_wav()
        r = api("POST", f"/api/mp/tasks/{task_id}/claims", token=sp_token,
                body={"word_ids": [w1.id, w2.id]})
        c = j(r)
        check("领取 2 词条归我专有", r.status_code == 200 and len(c.get("claimed_word_ids", [])) == 2
              and c["stats"]["my_claimed"] == 2 and c["stats"]["available"] == 0
              and c["stats"]["claimable"] == 0,
              str(r.status_code) + " " + str(j(r)))
        sp2 = Speaker(device_id=DEVICE + "_2", nickname="端到端验证第二人")
        db.add(sp2)
        db.flush()
        db.commit()
        sp2_token = create_access_token({"speaker_id": sp2.id, "openid": "", "role": "speaker"})
        SP2 = {"Authorization": "Bearer " + sp2_token}
        r = api("GET", "/api/mp/agreements")
        ag = j(r) if r.status_code == 200 else []
        api("POST", "/api/mp/agreements/accept", token=sp2_token,
            body={"accepted": [{"type": a["type"], "version": a["version"]} for a in ag]})
        r = api("POST", "/api/mp/team/join", token=sp2_token, body={"code": TEAM})
        check("第二人绑定同团队", r.status_code == 200, str(r.status_code) + " " + str(j(r)))
        r = api("POST", f"/api/mp/tasks/{task_id}/claims", token=sp2_token,
                body={"word_ids": [w1.id]})
        check("第二人抢领已被领词条 409", r.status_code == 409,
              str(r.status_code) + " " + str(j(r)))
        r = requests.post(BASE + "/api/mp/recordings", headers=SP2,
                          data={"task_id": str(task_id), "word_id": str(w1.id),
                                "duration": "1000", "device_id": DEVICE + "_2"},
                          files={"file": ("vfy.wav", wav, "audio/wav")}, timeout=15)
        check("第二人未领上传 403", r.status_code == 403 and "未被你领取" in str(j(r)),
              str(r.status_code) + " " + str(j(r)))

        # —— 7.6 领取制：/words 只返回我领取的词条 ——
        r = api("GET", f"/api/mp/tasks/{task_id}/words", token=sp_token)
        words = j(r).get("items", [])
        check("任务词条 2 条且未录（仅已领）", r.status_code == 200 and j(r).get("total") == 2
              and all(w["recorded"] is False for w in words)
              and j(r)["claim"]["my_claimed"] == 2,
              f"total={j(r).get('total')} statuses={[w['status'] for w in words]}")

        # —— 8. 上传 2 条录音（WAV 1s，均已领取）——
        rec_ids = {}
        for wid, tag in ((w1.id, "词条一"), (w2.id, "词条二")):
            rr = requests.post(BASE + "/api/mp/recordings", headers=SP,
                               data={"task_id": str(task_id), "word_id": str(wid),
                                     "duration": "1000", "device_id": DEVICE},
                               files={"file": ("vfy.wav", wav, "audio/wav")}, timeout=15)
            rec_ids[wid] = j(rr).get("recording_id") if rr.status_code == 200 else None
            check(f"上传录音 {tag}", rr.status_code == 200 and rec_ids[wid],
                  str(rr.status_code) + " " + str(j(rr)))
        rec1, rec2 = rec_ids[w1.id], rec_ids[w2.id]

        # —— 9. 后台审核：待审 2 条 → 通过一条 / 驳回另一条 ——
        r = api("GET", "/api/review/recordings", token=SUPER, params={"task_id": task_id})
        rl = j(r).get("items", [])
        check("审核列表待审 2 条", r.status_code == 200 and j(r).get("total") == 2
              and all(i["status"] == "pending" for i in rl), f"total={j(r).get('total')}")
        r = api("POST", f"/api/review/recordings/{rec1}/verdict", token=SUPER,
                body={"approved": True, "note": ""})
        check("审核通过 rec1", r.status_code == 200 and j(r).get("status") == "approved",
              str(r.status_code) + " " + str(j(r)))
        r = api("POST", f"/api/review/recordings/{rec2}/verdict", token=SUPER,
                body={"approved": False, "note": "音质不佳需重录"})
        check("审核驳回 rec2", r.status_code == 200 and j(r).get("status") == "rejected",
              str(r.status_code) + " " + str(j(r)))
        r = api("GET", f"/api/mp/tasks/{task_id}/words", token=sp_token)
        st = {w["word_id"]: w["status"] for w in j(r).get("items", [])}
        check("发音人侧词条状态同步", st.get(w1.id) == "approved" and st.get(w2.id) == "rejected",
              f"statuses={st}")

        # —— 10. 导出 ZIP：manifest 仅含已通过 rec1 + 音频文件 ——
        r = api("GET", "/api/review/export", token=SUPER, params={"task_id": task_id})
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/zip"):
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            names = zf.namelist()
            manifest = zf.read("manifest.csv").decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(manifest)))
            audio_names = [n for n in names if n.startswith("audios/")]
            ok = (len(rows) == 1 and int(rows[0]["recording_id"]) == rec1
                  and rows[0]["audio_present"] == "1" and len(audio_names) == 1)
            check("导出 ZIP 仅含已通过录音", ok,
                  f"rows={[row['recording_id'] for row in rows]} audio={audio_names}")
        else:
            check("导出 ZIP 仅含已通过录音", False, str(r.status_code) + " " + str(j(r)))

        # —— 11. 内容安全确定性单测（进程内 monkeypatch，不触公网）——
        orig_get_token, orig_post, orig_secret = cs.get_access_token, cs._wechat_post, cs.settings.WECHAT_SECRET
        try:
            cs.get_access_token = lambda: "test-token"
            cs._wechat_post = lambda url, token, body: {"errcode": 87014, "errmsg": "risky"}
            r1 = cs.check_text("违规内容测试")
            check("check_text 87014 → blocked", r1.blocked is True and r1.passed is False,
                  f"blocked={r1.blocked}")
            cs._wechat_post = lambda url, token, body: {"errcode": 0, "errmsg": "ok"}
            r2 = cs.check_text("正常内容测试")
            check("check_text errcode=0 → 放行", r2.blocked is False and r2.passed is True,
                  f"blocked={r2.blocked}")

            def boom(url, token, body):
                raise requests.RequestException("net down")
            cs._wechat_post = boom
            r3 = cs.check_text("内容")
            check("check_text 网络异常 fail-open", r3.blocked is False and r3.passed is True,
                  f"blocked={r3.blocked}")
            cs._wechat_post = lambda url, token, body: {"trace_id": "trace_abc"}
            tid = cs.check_media_async("", "https://example.com/a.wav")
            check("check_media_async 返回 trace_id", tid == "trace_abc", str(tid))

            # 无 Secret：get_access_token/check_media_async → None，check_text 放行
            cs.settings.WECHAT_SECRET = ""
            cs.get_access_token = orig_get_token
            check("无 Secret get_access_token → None", cs.get_access_token() is None)
            check("无 Secret check_media_async → None",
                  cs.check_media_async("", "https://example.com/a.wav") is None)
            r5 = cs.check_text("违规内容")
            check("无 Secret check_text fail-open", r5.blocked is False and r5.passed is True,
                  f"blocked={r5.blocked}")

            # 无公网地址：fire_media_check 直接跳过不抛错（MEDIA_PUBLIC_BASE 空）
            try:
                cs.fire_media_check(rec1)
                check("fire_media_check 无公网地址不抛错", True)
            except Exception as exc:
                check("fire_media_check 无公网地址不抛错", False, str(exc))
        finally:
            cs.settings.WECHAT_SECRET = orig_secret
            cs.get_access_token = orig_get_token
            cs._wechat_post = orig_post

        # —— 12. 我的时长统计 + 导出 ——
        r = api("GET", "/api/mp/me/durations", token=sp_token)
        d = j(r)
        check("me/durations 1通过+1驳回", d.get("total_count") == 2 and d.get("approved_count") == 1
              and d.get("rejected_count") == 1 and d.get("pending_count") == 0,
              f"{ {k: d.get(k) for k in ('total_count','approved_count','rejected_count','pending_count')} }")
        r = api("GET", "/api/mp/me/export", token=sp_token)
        csv_text = r.content.decode("utf-8-sig") if r.status_code == 200 else ""
        row_n = len(list(csv.reader(io.StringIO(csv_text)))) - 1 if csv_text else 0
        check("me/export CSV 含 2 行", r.status_code == 200 and row_n == 2,
              f"status={r.status_code} rows={row_n}")

        # —— 12.5 重录被驳回录音：旧驳回原因/备注应清空、状态回待审（后台完善 2）——
        rdb = db.get(Recording, rec2)
        rdb.reject_reasons = "noise"
        rdb.review_note = "音质不佳需重录"
        db.commit()
        rr = requests.post(BASE + "/api/mp/recordings", headers=SP,
                           data={"task_id": str(task_id), "word_id": str(w2.id),
                                 "duration": "1000", "device_id": DEVICE},
                           files={"file": ("vfy.wav", wav, "audio/wav")}, timeout=15)
        db.refresh(rdb)
        check("重录被驳回录音 → 状态回待审 + 原因/备注清空",
              rr.status_code == 200 and rdb.status == "pending"
              and rdb.reject_reasons is None and rdb.review_note is None,
              str(rr.status_code) + " " + str(j(rr))[:80] + f" reasons={rdb.reject_reasons}")

        # —— 12.6 质量预警：暂停上传 → 403；恢复 → 可传（后台完善 3）——
        r = api("PATCH", f"/api/speakers/{sp.id}", token=SUPER, body={"upload_paused": True})
        check("暂停发音人上传 → 200 且 upload_paused=true",
              r.status_code == 200 and r.json().get("upload_paused") is True,
              str(r.status_code) + " " + str(j(r))[:80])
        rr = requests.post(BASE + "/api/mp/recordings", headers=SP,
                           data={"task_id": str(task_id), "word_id": str(w2.id),
                                 "duration": "1000", "device_id": DEVICE},
                           files={"file": ("vfy.wav", wav, "audio/wav")}, timeout=15)
        check("暂停后上传 → 403 已被暂停",
              rr.status_code == 403 and "暂停上传" in rr.text,
              str(rr.status_code) + " " + str(j(rr))[:80])
        r = api("PATCH", f"/api/speakers/{sp.id}", token=SUPER, body={"upload_paused": False})
        check("恢复发音人上传 → 200 且 upload_paused=false",
              r.status_code == 200 and r.json().get("upload_paused") is False,
              str(r.status_code) + " " + str(j(r))[:80])
        rr = requests.post(BASE + "/api/mp/recordings", headers=SP,
                           data={"task_id": str(task_id), "word_id": str(w2.id),
                                 "duration": "1000", "device_id": DEVICE},
                           files={"file": ("vfy.wav", wav, "audio/wav")}, timeout=15)
        check("恢复后上传 → 200 覆盖成功",
              rr.status_code == 200, str(rr.status_code) + " " + str(j(rr))[:80])

    finally:
        cleanup(db)
        db.close()
        results.append("[INFO] 已清理：VFY0- 团队码/词条/任务/录音/发音人")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    passed = sum(1 for x in results if x.startswith("[PASS]"))
    failed = sum(1 for x in results if x.startswith("[FAIL]"))
    print(f"done: {passed} passed, {failed} failed -> {OUT}")


if __name__ == "__main__":
    main()
