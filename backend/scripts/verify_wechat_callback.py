"""media_check_async 微信回调回写验证：进程内单元测试 + 对运行中服务的 HTTP 测试。

覆盖：
- verify_signature / parse_body / media_check_verdict 单元判定（JSON/XML/isrisky/errcode/suggest）
- 回调 POST 按 trace_id 回写录音状态：passed/blocked/failed
- XML 推送格式解析回写
- URL 验签 GET 回显 echostr；配 Token 后正确验签生效、错误验签被拒
- 幂等（重复推送不报错）
输出 UTF-8 写文件，避免 Git Bash 控制台 GBK 乱码。
用法: ./.venv/Scripts/python.exe scripts/verify_wechat_callback.py
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.services import wechat_push as wp  # noqa: E402

# 目标服务地址与配置的验签 Token（可被环境变量覆盖，用于独立端口起带 token 的服务实例）
BASE = os.environ.get("CBK_BASE", "http://127.0.0.1:8000")
TOKEN = os.environ.get("CBK_TOKEN", "")  # 空 = 服务器 fail-open 跳过验签
OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_wechat_callback.txt")

results = []
TRACE_PREFIX = "CBK-"

# 本轮签名字段
TS, NONCE = "1710000000", "cbknonce"


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def sha1sig(token, ts, nonce):
    return hashlib.sha1("".join(sorted([token, ts, nonce])).encode()).hexdigest()


def api_post(payload, sig_ok=None, trace=None):
    params = {"timestamp": TS, "nonce": NONCE}
    if TOKEN:
        # 默认带正确签名；显式 sig_ok=False 用于「错误签名被拒」用例
        params["signature"] = sha1sig(TOKEN, TS, NONCE) if sig_ok is not False else "deadbeef"
    else:
        params["signature"] = ""  # 服务器未配 token → fail-open 跳过验签
    return requests.post(BASE + "/api/wechat/callback", params=params,
                         data=payload, timeout=15)


def read_status(trace_id):
    db = SessionLocal()
    try:
        rec = db.query(Recording).filter(
            Recording.media_check_trace_id == trace_id).first()
        return rec.content_check_status if rec else None
    finally:
        db.close()


def make_recording(db, trace_id):
    rec = Recording(task_id=999001, word_id=999001, speaker_id=999001,
                    audio_url="/media/cbk-test.wav", status="pending",
                    content_check_status="media_pending",
                    media_check_trace_id=trace_id)
    db.add(rec)
    db.commit()
    return rec.id


def cleanup(db):
    db.query(Recording).filter(Recording.media_check_trace_id.like(TRACE_PREFIX + "%")).delete()
    db.commit()


def main():
    db = SessionLocal()
    cleanup(db)

    # —— 0. 单元测试（确定性，不依赖 HTTP/网络）——
    check("验签：空 token 跳过(fail-open)", wp.verify_signature("", TS, NONCE, "anything"))
    check("验签：正确签名通过", wp.verify_signature("tok", TS, NONCE, sha1sig("tok", TS, NONCE)))
    check("验签：错误签名拒绝",
          not wp.verify_signature("tok", TS, NONCE, sha1sig("bad", TS, NONCE)))
    check("验签：缺 signature 拒绝", not wp.verify_signature("tok", TS, NONCE, ""))

    v, _ = wp.media_check_verdict({"isrisky": 0})
    check("判定：isrisky=0 → passed", v == "passed", v)
    v, _ = wp.media_check_verdict({"isrisky": 1})
    check("判定：isrisky=1 → blocked", v == "blocked", v)
    v, _ = wp.media_check_verdict({"errcode": -1008})
    check("判定：errcode=-1008 → failed", v == "failed", v)
    v, _ = wp.media_check_verdict({"result": {"suggest": "risky"}})
    check("判定：result.suggest=risky → blocked", v == "blocked", v)
    v, _ = wp.media_check_verdict({"result": {"suggest": "pass"}})
    check("判定：result.suggest=pass → passed", v == "passed", v)
    v, _ = wp.media_check_verdict({"detail": [{"suggest": "risky"}]})
    check("判定：detail[].suggest=risky → blocked", v == "blocked", v)
    v, _ = wp.media_check_verdict({})
    check("判定：缺字段 → unknown 不误判", v == "unknown", v)

    p = wp.parse_body(b'{"Event": "wxa_media_check", "trace_id": "x"}')
    check("解析：JSON", p and p.get("Event") == "wxa_media_check" and p.get("trace_id") == "x",
          str(p)[:80])
    p = wp.parse_body(b'<xml><Event>wxa_media_check</Event><trace_id>x</trace_id></xml>')
    check("解析：XML", p and p.get("Event") == "wxa_media_check" and p.get("trace_id") == "x",
          str(p)[:80])
    check("解析：空体 → None", wp.parse_body(b"") is None)

    # —— 1. HTTP：JSON isrisky=0 → media_passed ——
    t1 = TRACE_PREFIX + "PASS"
    r1 = make_recording(db, t1)
    payload = json.dumps({
        "ToUserName": "gh_test", "FromUserName": "o_test", "CreateTime": 1710000000,
        "MsgType": "event", "Event": "wxa_media_check",
        "isrisky": 0, "errcode": 0, "errmsg": "ok", "status_code": 0,
        "trace_id": t1, "result": {"suggest": "pass", "label": 100},
    })
    r = api_post(payload)
    check("回写 isrisky=0 → media_passed",
          r.status_code == 200 and r.text == "success"
          and read_status(t1) == "media_passed",
          f"HTTP {r.status_code} {r.text[:40]} status={read_status(t1)}")
    # 幂等：重复推送
    r = api_post(payload)
    check("重复推送幂等不报错", r.status_code == 200 and read_status(t1) == "media_passed",
          str(r.status_code))

    # —— 2. HTTP：isrisky=1 → media_blocked ——
    t2 = TRACE_PREFIX + "BLOCK"
    make_recording(db, t2)
    r = api_post(json.dumps({"Event": "wxa_media_check", "isrisky": 1, "errcode": 0,
                             "trace_id": t2, "result": {"suggest": "risky"},
                             "detail": [{"suggest": "risky", "label": 10001}]}))
    check("回写 isrisky=1 → media_blocked",
          r.status_code == 200 and read_status(t2) == "media_blocked",
          f"status={read_status(t2)}")

    # —— 3. HTTP：errcode=-1008（下载失败）→ media_failed ——
    t3 = TRACE_PREFIX + "FAIL"
    make_recording(db, t3)
    r = api_post(json.dumps({"Event": "wxa_media_check", "errcode": -1008,
                             "trace_id": t3, "result": {"suggest": "pass"}}))
    check("回写 errcode=-1008 → media_failed",
          r.status_code == 200 and read_status(t3) == "media_failed",
          f"status={read_status(t3)}")

    # —— 4. HTTP：XML 推送格式回写 ——
    t4 = TRACE_PREFIX + "XML"
    make_recording(db, t4)
    xml_body = (f"<xml><ToUserName>gh_test</ToUserName><FromUserName>o_test</FromUserName>"
                f"<CreateTime>1710000000</CreateTime><MsgType>event</MsgType>"
                f"<Event>wxa_media_check</Event><isrisky>0</isrisky><errcode>0</errcode>"
                f"<status_code>0</status_code><trace_id>{t4}</trace_id>"
                f"<result><suggest>pass</suggest></result></xml>")
    r = api_post(xml_body)
    check("XML 推送 → media_passed", r.status_code == 200 and read_status(t4) == "media_passed",
          f"status={read_status(t4)}")

    # —— 5. 非内容安全事件被忽略，不报错 ——
    r = api_post(json.dumps({"ToUserName": "gh_test", "Event": "subscribe"}))
    check("非内容安全事件忽略", r.status_code == 200 and r.text == "success", str(r.status_code))

    # —— 6/7. 签名路径：按服务器实际配置的 TOKEN 断言 ——
    if not TOKEN:
        # 服务器未配 token（fail-open）：任意签名 GET 都回显 echostr，POST 不验签
        r = requests.get(BASE + "/api/wechat/callback",
                         params={"signature": "whatever", "timestamp": TS,
                                 "nonce": NONCE, "echostr": "CBK-ECHO-1"}, timeout=15)
        check("GET 验签回显 echostr（未配 token，fail-open）",
              r.status_code == 200 and r.text == "CBK-ECHO-1",
              f"HTTP {r.status_code} body={r.text[:40]}")
        results.append("[SKIP] 签名路径（POST 错误签名拒绝）需服务器配置 WECHAT_MSG_TOKEN，跳过")
    else:
        # 服务器配了 token：正确验签回写、错误验签被拒、GET 同规则
        t5 = TRACE_PREFIX + "SIG"
        make_recording(db, t5)
        payload = json.dumps({"Event": "wxa_media_check", "isrisky": 0, "errcode": 0,
                              "trace_id": t5, "result": {"suggest": "pass"}})
        r = api_post(payload, sig_ok=True)
        check("配 Token：正确签名 → media_passed",
              r.status_code == 200 and read_status(t5) == "media_passed",
              f"status={read_status(t5)}")
        r = api_post(payload, sig_ok=False)
        check("配 Token：错误签名被拒且不改状态",
              r.status_code == 200 and r.text == "success" and read_status(t5) == "media_passed",
              f"status={read_status(t5)}")
        r = requests.get(BASE + "/api/wechat/callback",
                         params={"signature": sha1sig(TOKEN, TS, NONCE),
                                 "timestamp": TS, "nonce": NONCE, "echostr": "CBK-ECHO-2"},
                         timeout=15)
        check("配 Token：GET 正确验签回显 echostr",
              r.status_code == 200 and r.text == "CBK-ECHO-2", r.text[:40])
        r = requests.get(BASE + "/api/wechat/callback",
                         params={"signature": "bad", "timestamp": TS,
                                 "nonce": NONCE, "echostr": "NOPE"}, timeout=15)
        check("配 Token：GET 错误验签返回 signature error",
              r.status_code == 200 and r.text != "NOPE", r.text[:40])

    cleanup(db)
    db.close()

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    passed = sum(1 for x in results if x.startswith("[PASS]"))
    failed = sum(1 for x in results if x.startswith("[FAIL]"))
    print(f"RESULT: {passed} PASS / {failed} FAIL (详见 {OUT})")


if __name__ == "__main__":
    main()
