"""阶段八·任务↔团队码关联 验证：团队校验 / 地区带出 / 越省拦截 / 改绑解绑。

通过运行中的服务 HTTP 调用验证；输出 UTF-8 写文件，避免 Git Bash 控制台 GBK 乱码。
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

BASE = "http://127.0.0.1:8000"
OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_task_team_code.txt")

lines = []
def log(s=""):
    lines.append(str(s))
    print(str(s), flush=True)

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

def expect(cond, name, extra=""):
    extra = str(extra)
    log(("PASS " if cond else "FAIL ") + name + (("  " + extra) if extra else ""))

from app.db import SessionLocal
from app.models.task import TaskBatch
from app.models.team_code import TeamCode

db = SessionLocal()
PREFIX = "VFY9-"

# 0) 登录
r = api("POST", "/api/auth/login", body={"username": "admin", "password": "admin123"})
expect(r.status_code == 200, "超管登录", str(r.status_code))
SUPER = r.json()["access_token"]

r = api("POST", "/api/auth/login", body={"username": "hebei_admin", "password": "admin123"})
expect(r.status_code == 200, "省管理员登录", str(r.status_code))
HB = r.json()["access_token"]

# 1) 准备测试团队（清掉历史验证残留，避免一码一区/唯一码冲突）
for tc in db.query(TeamCode).filter(TeamCode.code.like(PREFIX + "%")).all():
    db.delete(tc)
# 清理历史验证任务
from app.models.task import TaskBatchItem
for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证任务%")).all():
    db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
    db.delete(t)
db.commit()

# 石家庄团队复用已有真实团队 HB-SJZ（一码一区，13/1301 已被占用）
team_sjz = db.query(TeamCode).filter(TeamCode.code == "HB-SJZ").first()
expect(team_sjz is not None, "复用已有团队 HB-SJZ (13/1301)")

# 沈阳团队：新建 21/2101
r = api("POST", "/api/team-codes", token=SUPER,
        body={"code": PREFIX + "SY", "name": "沈阳验证团队", "province_code": "21", "city_code": "2101"})
ok = r.status_code == 200
expect(ok, "创建团队码 VFY9-SY", str(r.status_code) + " " + str(j(r)))
team_sy = r.json().get("id") if ok else None

TEAM_SJZ = "HB-SJZ"  # 石家庄真实团队 13/1301

# 2) 关联团队创建任务：地区由团队码带出
r = api("POST", "/api/tasks", token=SUPER, body={
    "name": "验证任务A-关联石家庄", "province_code": "13", "city_code": "1301",
    "team_code": TEAM_SJZ, "required_audio_count": 30, "word_ids": [],
})
ok = r.status_code == 200
extra = j(r) if not ok else f"team_code={j(r).get('team_code')} prov={j(r).get('province_code')} city={j(r).get('city_code')}"
expect(ok and j(r).get("team_code") == TEAM_SJZ and j(r).get("city_code") == "1301",
       "创建任务关联团队码并带出地区", str(r.status_code) + " " + str(extra))
task_a = r.json().get("id") if ok else None

# 3) 关联团队但地区与团队不一致 → 422
r = api("POST", "/api/tasks", token=SUPER, body={
    "name": "验证任务B-地区错配", "province_code": "21", "city_code": "2101",
    "team_code": TEAM_SJZ, "word_ids": [],
})
expect(r.status_code == 422 and "地区" in str(j(r)), "关联团队但地区不一致拒绝", str(r.status_code) + " " + str(j(r)))

# 4) 无效团队码 → 422
r = api("POST", "/api/tasks", token=SUPER, body={
    "name": "验证任务C-无效团队", "province_code": "13", "city_code": "1301",
    "team_code": PREFIX + "NOPE", "word_ids": [],
})
expect(r.status_code == 422 and "团队码不存在" in str(j(r)), "无效团队码拒绝", str(r.status_code) + " " + str(j(r)))

# 5) 省管理员用本省团队创建 → 200
r = api("POST", "/api/tasks", token=HB, body={
    "name": "验证任务D-省管理员本省团队", "province_code": "13", "city_code": "1301",
    "team_code": TEAM_SJZ, "word_ids": [],
})
ok = r.status_code == 200
expect(ok and j(r).get("team_code") == TEAM_SJZ, "省管理员本省团队创建", str(r.status_code) + " " + str(j(r)))
task_d = r.json().get("id") if ok else None

# 6) 省管理员用他省团队 → 403
r = api("POST", "/api/tasks", token=HB, body={
    "name": "验证任务E-省管理员越省团队", "province_code": "13", "city_code": "1301",
    "team_code": PREFIX + "SY", "word_ids": [],
})
expect(r.status_code == 403 and "本省" in str(j(r)), "省管理员越省团队拒绝", str(r.status_code) + " " + str(j(r)))

# 7) list_tasks 按 team_code 筛选 + 返回含 team_code
r = api("GET", "/api/tasks", token=SUPER, params={"team_code": TEAM_SJZ})
items = j(r).get("items", [])
expect(all(i.get("team_code") == TEAM_SJZ for i in items) and len(items) >= 2,
       "list_tasks 按团队码筛选", f"{len(items)}条 team_codes={[i.get('team_code') for i in items]}")

# 8) 改绑团队：地区更新
r = api("PATCH", f"/api/tasks/{task_a}", token=SUPER, body={"team_code": PREFIX + "SY"})
ok = r.status_code == 200
extra = j(r) if not ok else f"team={j(r).get('team_code')} prov={j(r).get('province_code')} city={j(r).get('city_code')} district={j(r).get('district_code')}"
expect(ok and j(r).get("team_code") == PREFIX + "SY" and j(r).get("province_code") == "21",
       "编辑任务改绑团队后地区带出", str(r.status_code) + " " + str(extra))

# 9) 解除关联：保留地区，team_code 清空
r = api("PATCH", f"/api/tasks/{task_a}", token=SUPER, body={"team_code": None})
ok = r.status_code == 200
extra = j(r) if not ok else f"team={j(r).get('team_code')} prov={j(r).get('province_code')}"
expect(ok and j(r).get("team_code") is None and j(r).get("province_code") == "21",
       "编辑任务解除团队关联保留地区", str(r.status_code) + " " + str(extra))

# 10) 编辑已发布任务改绑 → 400（仅草稿可编辑；task_a 仍是草稿，跳过）
r = api("PATCH", f"/api/tasks/{task_d}", token=HB, body={"team_code": PREFIX + "SY"})
expect(r.status_code == 403 and "本省" in str(j(r)), "省管理员编辑任务越省团队拒绝", str(r.status_code) + " " + str(j(r)))

# 11) 超管可直接跨省改绑（任务本就全国可管）
r = api("PATCH", f"/api/tasks/{task_d}", token=SUPER, body={"team_code": PREFIX + "SY"})
ok = r.status_code == 200
expect(ok and j(r).get("team_code") == PREFIX + "SY" and j(r).get("province_code") == "21",
       "超管跨省改绑任务", str(r.status_code) + " " + str(j(r)))

# 清理验证数据（含调试残留 验证DBG）
for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证%")).all():
    api("DELETE", f"/api/tasks/{t.id}", token=SUPER)
for tc in db.query(TeamCode).filter(TeamCode.code.like(PREFIX + "%")).all():
    db.delete(tc)
db.commit()

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
log()
log("结果已写入 " + OUT)
