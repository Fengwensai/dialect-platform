"""阶段八 全流程验证：团队码管理 + 发音人属地纠错 + 小程序端严格属地隔离。

通过运行中的服务 HTTP 调用验证；发音人 token 直接 mint（真实 WECHAT_SECRET 会拒绝假 wx code）。
输出 UTF-8 写文件，避免 Git Bash 控制台 GBK 乱码。
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from sqlalchemy import text  # noqa: E402

BASE = "http://127.0.0.1:8000"
OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_region_isolation.txt")

lines = []
def log(s=""):
    lines.append(str(s))
    print(str(s), flush=True)

def api(method, path, token=None, body=None, files=None, **kw):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if files:
        return requests.request(method, BASE + path, headers=headers, data=body, files=files, timeout=15)
    kwargs = {}
    if body is not None:
        kwargs["json"] = body
    return requests.request(method, BASE + path, headers=headers, **kwargs, timeout=15)

def j(r):
    try:
        return r.json()
    except Exception:
        return r.text[:200]

def expect(cond, name, extra=""):
    extra = str(extra)
    log(("PASS " if cond else "FAIL ") + name + (("  " + extra) if extra else ""))

def accept_agreements(token):
    """发音人先同意最新版协议，解除阶段九协议门禁（守卫接口要求）。"""
    r = api("GET", "/api/mp/agreements")
    ag = r.json() if r.status_code == 200 else []
    body = {"accepted": [{"type": a["type"], "version": a["version"]} for a in ag]}
    api("POST", "/api/mp/agreements/accept", token=token, body=body)

# 从 app 直接 mint 发音人 token（不走 wx.login）
from app.core.security import create_access_token
from app.db import SessionLocal
from app.models.speaker import Speaker
from app.models.task import TaskBatch
from app.models.team_code import TeamCode
from app.models.recording import Recording
from app.models.task import TaskBatchItem

db = SessionLocal()

# 1) 管理员登录
r = api("POST", "/api/auth/login", body={"username": "admin", "password": "admin123"})
expect(r.status_code == 200, "超管登录", str(r.status_code))
SUPER = r.json()["access_token"]

r = api("POST", "/api/auth/login", body={"username": "hebei_admin", "password": "admin123"})
expect(r.status_code == 200, "省管理员登录", str(r.status_code))
HB = r.json()["access_token"]

# 2) 团队码 CRUD
prefix = "VFY8-"
# 清掉历史验证数据
for tc in db.query(TeamCode).filter(TeamCode.code.like(prefix + "%")).all():
    db.delete(tc)
db.commit()

codes = {}
# 13/1301 已有真实团队 HB-SJZ（一码一区），测试发音人直接绑定它
for code, name, prov, city in [
    (prefix + "SY", "沈阳验证团队", "21", "2101"),
    (prefix + "HB-LF", "廊坊验证团队", "13", "1310"),
]:
    r = api("POST", "/api/team-codes", token=SUPER,
            body={"code": code, "name": name, "province_code": prov, "city_code": city})
    ok = r.status_code == 200
    expect(ok, f"创建团队码 {code}", j(r))
    codes[code] = r.json()["id"] if ok else None

# 一码一区：同省同市再建 → 400
r = api("POST", "/api/team-codes", token=SUPER,
        body={"code": prefix + "SY2", "name": "重复", "province_code": "21", "city_code": "2101"})
expect(r.status_code == 400 and "一码一区" in str(j(r)), "一码一区重复区拒绝", str(r.status_code) + " " + str(j(r)))

# 重复码 → 400
r = api("POST", "/api/team-codes", token=SUPER,
        body={"code": prefix + "SY", "name": "重复码", "province_code": "13", "city_code": "1301"})
expect(r.status_code == 400 and "已存在" in str(j(r)), "重复团队码拒绝", str(r.status_code))

# 城市不属于省 → 422
r = api("POST", "/api/team-codes", token=SUPER,
        body={"code": prefix + "BAD", "name": "错配", "province_code": "21", "city_code": "1301"})
expect(r.status_code == 422, "错配省市拒绝", str(r.status_code) + " " + str(j(r)))

# 省管理员越省创建 → 403
r = api("POST", "/api/team-codes", token=HB,
        body={"code": prefix + "SYX", "name": "越省", "province_code": "21", "city_code": "2101"})
expect(r.status_code == 403, "省管理员越省创建拒绝", str(r.status_code))

# 省管理员列表仅本省
r = api("GET", "/api/team-codes", token=HB)
hb_list = j(r)
expect(all(tc["province_code"] == "13" for tc in hb_list), "省管理员列表仅本省", f"{len(hb_list)}条")

# 改名
r = api("PATCH", f"/api/team-codes/{codes[prefix+'SY']}", token=SUPER, body={"name": "沈阳验证团队(改)"})
expect(r.status_code == 200 and r.json()["name"].endswith("(改)"), "团队码改名", str(j(r)))

# 3) 发音人准备（建 2 个：一个未绑定，一个 1301）
def make_speaker(device_id, nickname, bound_to=None):
    """创建/复用测试发音人；默认重置为未绑定（避免上一轮残留属地）。"""
    sp = db.query(Speaker).filter(Speaker.device_id == device_id).first()
    if sp is None:
        sp = Speaker(device_id=device_id, nickname=nickname, openid="verify_" + device_id)
        db.add(sp)
        db.commit()
        db.refresh(sp)
    sp.province_code = None
    sp.city_code = None
    sp.team_code = None
    if bound_to:
        sp.province_code, sp.city_code, sp.team_code = bound_to
    db.commit()
    db.refresh(sp)
    return sp

sp_unbound = make_speaker("verify_unbound", "未绑定发音人")
sp_1301 = make_speaker("verify_hb", "河北发音人", bound_to=("13", "1301", "HB-SJZ"))

tok_unbound = create_access_token({"speaker_id": sp_unbound.id, "openid": "", "role": "speaker"})
tok_1301 = create_access_token({"speaker_id": sp_1301.id, "openid": "", "role": "speaker"})
accept_agreements(tok_unbound)

# 4) 未绑定限制
r = api("GET", "/api/mp/tasks", token=tok_unbound)
expect(r.status_code == 200 and j(r) == {"total": 0, "items": []}, "未绑定→任务空", str(j(r)))

# 找 1301 已发布任务（若没有则创建）
from app.models.word import WordLibrary
task = db.query(TaskBatch).filter(
    TaskBatch.status == "published", TaskBatch.province_code == "13", TaskBatch.city_code == "1301"
).first()
if task is None:
    word = db.query(WordLibrary).filter(WordLibrary.province_code == "13").first()
    task = TaskBatch(
        name="验证-石家庄任务", province_code="13", city_code="1301",
        status="published", description="自动化验证",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    if word:
        db.add(TaskBatchItem(task_batch_id=task.id, word_id=word.id))
        db.commit()

# 5) 绑定后任务可见
r = api("POST", "/api/mp/team/join", token=tok_unbound, body={"code": "HB-SJZ"})
expect(r.status_code == 200, "发音人绑定团队码", str(r.status_code) + " " + str(j(r)))
joined = j(r)
expect(joined.get("province_code") == "13" and joined.get("city_code") == "1301" and joined.get("team_code") == "HB-SJZ",
       "绑定后属地正确", json.dumps(joined, ensure_ascii=False))

# 重复绑定 → 400
r = api("POST", "/api/mp/team/join", token=tok_unbound, body={"code": prefix + "SY"})
expect(r.status_code == 400 and "已绑定" in str(j(r)), "重复绑定拒绝", str(r.status_code) + " " + str(j(r)))

# 无效团队码 → 404（用全新未绑定发音人测）
sp_invalid = make_speaker("verify_invalid", "无效码发音人")
tok_invalid = create_access_token({"speaker_id": sp_invalid.id, "openid": "", "role": "speaker"})
accept_agreements(tok_invalid)

# 省管理员给“未绑定”发音人补本省市（用于第 6 节测试，保持未绑定状态）
sp_hb_unbound = make_speaker("verify_hb_unbound", "河北未绑定发音人")
r = api("POST", "/api/mp/team/join", token=tok_invalid, body={"code": prefix + "NOPE"})
expect(r.status_code == 404, "无效团队码拒绝", str(r.status_code) + " " + str(j(r)))

# 任务列表仅含本地区
r = api("GET", "/api/mp/tasks", token=tok_unbound)
tasks = j(r)
expect(r.status_code == 200 and all(t["province_code"] == "13" and t["city_code"] == "1301" for t in tasks["items"]),
       "绑定后任务仅本地区", f"共{len(tasks['items'])}条")

# 越区词表 → 403（构造一个沈阳已发布任务）
task_sy = db.query(TaskBatch).filter(
    TaskBatch.status == "published", TaskBatch.province_code == "21", TaskBatch.city_code == "2101"
).first()
if task_sy is None:
    word_sy = db.query(WordLibrary).filter(WordLibrary.province_code == "21").first()
    task_sy = TaskBatch(
        name="验证-沈阳任务", province_code="21", city_code="2101",
        status="published", description="自动化验证",
    )
    db.add(task_sy)
    db.commit()
    db.refresh(task_sy)
    if word_sy:
        db.add(TaskBatchItem(task_batch_id=task_sy.id, word_id=word_sy.id))
        db.commit()
        task_sy_word_id = word_sy.id
    else:
        task_sy_word_id = None
else:
    item = db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == task_sy.id).first()
    task_sy_word_id = item.word_id if item else None

if task_sy:
    r = api("GET", f"/api/mp/tasks/{task_sy.id}/words", token=tok_unbound)
    expect(r.status_code == 403, "跨区词表拒绝", str(r.status_code) + " " + str(j(r)))
    # 越区上传 → 403（词条归属该任务才能走到属地检查）
    if task_sy_word_id:
        r = api("POST", "/api/mp/recordings", token=tok_unbound,
                files={"file": ("t.wav", b"RIFFxxxx", "audio/wav")},
                body={"task_id": str(task_sy.id), "word_id": str(task_sy_word_id),
                      "duration": "1000", "device_id": sp_unbound.device_id,
                      "nickname": "跨区", "gender": "male", "age_bracket": "age18_30"})
        expect(r.status_code == 403, "跨区上传拒绝", str(r.status_code) + " " + str(j(r)))

# 本区上传（词条存在才测）：属地匹配应放行到后续校验（音频内容非法→不会真入库），
# 关键在状态码≠403/400-绑定
item = db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == task.id).first()
if item:
    r = api("POST", "/api/mp/recordings", token=tok_unbound,
            files={"file": ("t.wav", b"RIFF....WAVEfmt ", "audio/wav")},
            body={"task_id": str(task.id), "word_id": str(item.word_id),
                  "duration": "1000", "device_id": sp_unbound.device_id,
                  "nickname": "河北发音人", "gender": "male", "age_bracket": "age18_30"})
    log("本区上传状态: " + str(r.status_code) + " " + str(j(r))[:200])
    expect(r.status_code != 403 and not (r.status_code == 400 and "加入团队" in str(j(r))),
           "本区上传未被属地拦截（业务校验另行判断）", str(r.status_code))
    # 清理该假音频
    db.query(Recording).filter(Recording.speaker_id == sp_unbound.id,
                               Recording.task_id == task.id).delete()
    db.commit()

# 6) 管理端属地纠错
r = api("PATCH", f"/api/speakers/{sp_unbound.id}", token=SUPER,
        body={"gender": "male", "age_bracket": "age18_30", "province_code": "21", "city_code": "2101"})
ok = r.status_code == 200
expect(ok, "超管纠错属地→辽宁沈阳", str(j(r)))
r = api("GET", "/api/speakers", token=SUPER, params={"page": 1, "page_size": 100})
sp_row = next((x for x in j(r)["items"] if x["id"] == sp_unbound.id), None)
expect(sp_row is not None and sp_row.get("province_code") == "21" and sp_row.get("city_code") == "2101",
       "纠错后属地生效", json.dumps(sp_row, ensure_ascii=False))
expect(sp_row.get("team_code") is None, "纠错后团队码解除", str(sp_row.get("team_code")))

# 省管理员不能把发音人移出本省
r = api("PATCH", f"/api/speakers/{sp_1301.id}", token=HB,
        body={"province_code": "21", "city_code": "2101"})
expect(r.status_code == 403, "省管理员越省纠错拒绝", str(r.status_code) + " " + str(j(r)))

# 省管理员本省内改市（石家庄→廊坊）
r = api("PATCH", f"/api/speakers/{sp_1301.id}", token=HB,
        body={"city_code": "1310"})
ok = r.status_code == 200
expect(ok, "省管理员本省改市(石家庄→廊坊)", str(j(r)))
if ok:
    r = api("GET", "/api/speakers", token=HB, params={"page": 1, "page_size": 100})
    sp_row = next((x for x in j(r)["items"] if x["id"] == sp_1301.id), None)
    expect(sp_row and sp_row.get("city_code") == "1310" and sp_row.get("province_code") == "13",
           "省管理员改市生效", json.dumps(sp_row, ensure_ascii=False))

# 省管理员编辑“未绑定”发音人（可绑定到本省）
r = api("PATCH", f"/api/speakers/{sp_hb_unbound.id}", token=HB,
        body={"province_code": "13", "city_code": "1301"})
expect(r.status_code == 200, "省管理员给未绑定发音人补本省市", str(r.status_code) + " " + str(j(r)))

# 7) 删除团队码（已绑定发音人不受影响）：删 13/1310 的 VFY8-HB-LF，
#    sp_1301 已被省管理员改市到 1310，删除后属地应保留。
tc_id = codes.get(prefix + "HB-LF")
if tc_id:
    r = api("DELETE", f"/api/team-codes/{tc_id}", token=SUPER)
    expect(r.status_code == 200, "删除团队码", str(j(r)))
    r = api("GET", "/api/speakers", token=SUPER, params={"page": 1, "page_size": 100})
    sp_row = next((x for x in j(r)["items"] if x["id"] == sp_1301.id), None)
    expect(sp_row is not None and sp_row.get("province_code") == "13" and sp_row.get("city_code") == "1310",
           "删码后已绑定发音人属地保留", json.dumps(sp_row, ensure_ascii=False))

# 清理验证数据
for sp in db.query(Speaker).filter(Speaker.device_id.in_(["verify_unbound", "verify_hb", "verify_invalid", "verify_hb_unbound"])).all():
    db.query(Recording).filter(Recording.speaker_id == sp.id).delete()
    db.execute(text("DELETE FROM speaker_agreements WHERE speaker_id = :sid"), {"sid": sp.id})
    db.delete(sp)
for tc in db.query(TeamCode).filter(TeamCode.code.like(prefix + "%")).all():
    db.delete(tc)
for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证-%")).all():
    db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
    db.delete(t)
db.commit()

log("\n===== 验证完成，数据已清理 =====")
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
log("结果已写入 " + OUT)
