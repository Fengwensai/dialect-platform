"""协议功能验证（阶段九）：对运行中的服务跑全部守卫/同意/版本升级流程。

结果写 UTF-8 文件（Git Bash 控制台中文会 GBK 乱码）。
用法: ./.venv/Scripts/python.exe scripts/verify_agreements.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from app.core.security import create_access_token  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from sqlalchemy import text  # noqa: E402

BASE = "http://127.0.0.1:8000"
OUT = os.path.join(os.path.dirname(__file__), "verify_agreements_out.txt")

results = []


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def main():
    db = SessionLocal()
    try:
        # —— 准备：临时测试发音人 + 各角色 token ——
        sp = db.query(Speaker).filter(Speaker.device_id == "verify_agree_test").first()
        if sp is None:
            sp = Speaker(device_id="verify_agree_test", nickname="协议验证临时发音人")
            db.add(sp)
            db.flush()
        sp_id = sp.id
        db.commit()

        super_admin = db.query(AdminUser).filter(AdminUser.role == "super_admin").first()
        prov_admin = (
            db.query(AdminUser)
            .filter(AdminUser.role == "province_admin")
            .order_by(AdminUser.id)
            .first()
        )
        assert super_admin is not None and prov_admin is not None, "缺少种子管理员"

        sp_token = create_access_token(
            {"speaker_id": sp_id, "openid": "", "role": "speaker"}
        )
        super_token = create_access_token(
            {"admin_id": super_admin.id, "role": "super_admin"}
        )
        prov_token = create_access_token(
            {
                "admin_id": prov_admin.id,
                "role": "province_admin",
                "province_code": prov_admin.province_code,
            }
        )
        SP = {"Authorization": "Bearer " + sp_token}
        SUPER = {"Authorization": "Bearer " + super_token}
        PROV = {"Authorization": "Bearer " + prov_token}

        # —— 1. 公开获取协议：3 条 v1 ——
        r = requests.get(BASE + "/api/mp/agreements")
        check("GET /api/mp/agreements 公开可达 200", r.status_code == 200, f"status={r.status_code}")
        ag = r.json() if r.status_code == 200 else []
        check("三类协议各 1 条且 version=1", len(ag) == 3 and all(a["version"] == 1 for a in ag),
              f"types={[a['type'] for a in ag]}")
        v1_by_type = {a["type"]: a["version"] for a in ag}
        expect = ["user_agreement", "privacy_policy", "voice_auth"]
        check("类型顺序稳定", [a["type"] for a in ag] == expect, f"got={[a['type'] for a in ag]}")

        # —— 2. 守卫：未同意前功能接口 403 ——
        r = requests.get(BASE + "/api/mp/tasks", headers=SP)
        check("守卫：未同意 403", r.status_code == 403, f"status={r.status_code} detail={r.json().get('detail') if r.status_code==403 else ''}")
        check("403 detail 含协议提示", r.status_code == 403 and "请先同意" in r.json().get("detail", ""))

        # —— 3. pending 端点：初始应为 3 类 ——
        r = requests.get(BASE + "/api/mp/agreements/pending", headers=SP)
        check("GET /pending 初始 3 类", r.status_code == 200 and sorted(r.json()["pending_agreements"]) == sorted(expect),
              f"got={r.json() if r.status_code==200 else r.text}")

        # —— 4. 全部同意 v1 → 守卫解除 ——
        body = {"accepted": [{"type": t, "version": v1_by_type[t]} for t in expect]}
        r = requests.post(BASE + "/api/mp/agreements/accept", json=body, headers=SP)
        check("accept 三类 v1 → 200 且 pending 空", r.status_code == 200 and r.json()["pending_agreements"] == [],
              f"got={r.json() if r.status_code==200 else r.text}")
        r = requests.get(BASE + "/api/mp/tasks", headers=SP)
        check("守卫解除：tasks 200", r.status_code == 200, f"status={r.status_code}")
        r = requests.get(BASE + "/api/mp/agreements/pending", headers=SP)
        check("pending 已清空", r.status_code == 200 and r.json()["pending_agreements"] == [])
        # 幂等：重复 accept 仍 200
        r = requests.post(BASE + "/api/mp/agreements/accept", json=body, headers=SP)
        check("重复 accept 幂等 200", r.status_code == 200, f"status={r.status_code}")
        # 部分同意是合法请求（不算错）
        partial = {"accepted": [{"type": "privacy_policy", "version": v1_by_type["privacy_policy"]}]}
        r = requests.post(BASE + "/api/mp/agreements/accept", json=partial, headers=SP)
        check("部分同意幂等 200", r.status_code == 200, f"status={r.status_code}")

        # —— 5. 非法 type 422 ——
        r = requests.post(BASE + "/api/mp/agreements/accept",
                          json={"accepted": [{"type": "bogus", "version": 1}]}, headers=SP)
        check("非法 type 422", r.status_code == 422, f"status={r.status_code}")

        # —— 6. 超管升级 user_agreement → v2；省管理员无权限 ——
        v2 = {"type": "user_agreement", "title": "用户协议",
              "content": "《方言采集平台用户协议》\n\n（协议验证脚本生成的 v2 测试内容，验证后清理）"}
        r = requests.post(BASE + "/api/agreements", json=v2, headers=SUPER)
        check("超管发布新版本 v2", r.status_code == 200 and r.json()["version"] == 2,
              f"status={r.status_code} version={r.json().get('version') if r.status_code==200 else ''}")
        r = requests.get(BASE + "/api/agreements", headers=SUPER)
        ua = next((x for x in r.json() if x["type"] == "user_agreement"), None)
        check("GET /api/agreements 最新含 user_agreement v2",
              r.status_code == 200 and ua and ua["version"] == 2)
        r = requests.get(BASE + "/api/agreements", headers=PROV)
        check("省管理员访问协议管理 403", r.status_code == 403, f"status={r.status_code}")
        r = requests.get(BASE + "/api/agreements/history", params={"type": "user_agreement"}, headers=SUPER)
        check("history 返回 v2/v1 两版", r.status_code == 200 and [h["version"] for h in r.json()] == [2, 1],
              f"got={[h['version'] for h in r.json()] if r.status_code==200 else ''}")

        # —— 7. 版本升级后：守卫重新拦截；v1 accept 409；v2 accept 200 ——
        r = requests.get(BASE + "/api/mp/tasks", headers=SP)
        check("升级后守卫重新 403", r.status_code == 403, f"status={r.status_code}")
        r = requests.post(BASE + "/api/mp/agreements/accept",
                          json={"accepted": [{"type": "user_agreement", "version": 1}]}, headers=SP)
        check("旧版本 v1 提交 409", r.status_code == 409,
              f"status={r.status_code} detail={r.json().get('detail') if r.status_code==409 else ''}")
        r = requests.post(BASE + "/api/mp/agreements/accept",
                          json={"accepted": [{"type": "user_agreement", "version": 2}]}, headers=SP)
        check("新版本 v2 提交 200 且 pending 空",
              r.status_code == 200 and r.json()["pending_agreements"] == [],
              f"status={r.status_code} got={r.json() if r.status_code==200 else r.text}")
        r = requests.get(BASE + "/api/mp/tasks", headers=SP)
        check("再同意后守卫解除", r.status_code == 200, f"status={r.status_code}")

    finally:
        # —— 清理：删 v2 测试版本 + 临时发音人及其同意记录 ——
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM agreements WHERE type = 'user_agreement' AND version = 2")
            )
            conn.execute(
                text("DELETE FROM speaker_agreements WHERE speaker_id = :sid"), {"sid": sp_id}
            )
        db.query(Speaker).filter(Speaker.id == sp_id).delete(synchronize_session=False)
        db.commit()
        db.close()
        results.append("[INFO] 已清理：v2 测试版本、临时发音人及同意记录")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    passed = sum(1 for x in results if x.startswith("[PASS]"))
    failed = sum(1 for x in results if x.startswith("[FAIL]"))
    print(f"done: {passed} passed, {failed} failed -> {OUT}")


if __name__ == "__main__":
    main()
