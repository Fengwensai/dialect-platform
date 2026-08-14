"""数据看板专项验证（进程内 TestClient，无需独立服务进程）。

覆盖看板三个端点的核心语义（全部确定性断言）：
- summary：聚合数字正确（发音人/录音/待审/通过/驳回/时长/通过率/活跃任务/团队/已录词条）
- summary 省管理员钳制：hebei_admin 只含本省（排除北京数据），区域分布按市级
- speakers：keyword 过滤分页、每行指标（recording/pending/approved/时长/任务数/词条数/最近活跃）、
  5 种排序（recording/approved/duration/last_active/created）相对顺序、性别/年龄段/团队筛选
- claims：词条/任务名/recorded 正确、越省 403、不存在 404

说明：summary 是全表聚合（dev 库已有其他数据），用「基线+增量」断言确定性；
speakers 列表用 device_id 前缀 keyword 锁定种子子集。
依赖：httpx（fastapi.testclient）。
用法: ./.venv/Scripts/python.exe scripts/verify_dashboard.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_dashboard.txt")
results = []

HB_PROV, HB_CITY = "13", "1301"  # 河北省石家庄
BJ_PROV, BJ_CITY = "11", "1101"  # 北京市
HB_TEAM, BJ_TEAM = "VFY-DASH-HB", "VFY-DASH-BJ"


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def snap_summary(db, scope):
    """与 dashboard.summary 同口径的基线快照（scope=None 全国 / '13' 本省）。"""
    sp_q = db.query(Speaker)
    rec_q = db.query(Recording).join(Speaker, Recording.speaker_id == Speaker.id)
    task_q = db.query(TaskBatch).filter(TaskBatch.status == "published")
    if scope:
        sp_q = sp_q.filter(Speaker.province_code == scope)
        rec_q = rec_q.filter(Speaker.province_code == scope)
        task_q = task_q.filter(TaskBatch.province_code == scope)
    base = {
        "speaker_total": sp_q.count(),
        "team_total": sp_q.with_entities(Speaker.team_code)
        .filter(Speaker.team_code.isnot(None)).distinct().count(),
        "rec": {},
        "active_task": task_q.count(),
        "distinct_word": rec_q.with_entities(func.count(func.distinct(Recording.word_id))).scalar() or 0,
        "region_sp": {},
        "region_rec": {},
    }
    for st, cnt, dur in (
        rec_q.with_entities(Recording.status, func.count(Recording.id),
                            func.sum(Recording.audio_duration))
        .group_by(Recording.status).all()
    ):
        base["rec"][st] = (cnt, dur or 0)
    group_col = Speaker.city_code if scope else Speaker.province_code
    for code, cnt in sp_q.with_entities(group_col, func.count(Speaker.id)).group_by(group_col).all():
        base["region_sp"][code] = cnt
    for code, cnt in (
        rec_q.with_entities(group_col, func.count(Recording.id)).group_by(group_col).all()
    ):
        base["region_rec"][code] = cnt
    return base


def get(base, key, default):
    return base[key] if key in base else default


def snap_trends(db, scope, days):
    """与 dashboard.trends 同口径：近 days 天各状态录音数（按属地钳制）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rec_q = db.query(Recording).join(Speaker, Recording.speaker_id == Speaker.id)
    if scope:
        rec_q = rec_q.filter(Speaker.province_code == scope)
    rows = rec_q.filter(Recording.created_at >= cutoff).with_entities(
        Recording.status, func.count(Recording.id)).group_by(Recording.status).all()
    counts = {st: cnt for st, cnt in rows}
    return {
        "total": sum(counts.values()),
        "pending": counts.get("pending", 0),
        "approved": counts.get("approved", 0),
        "rejected": counts.get("rejected", 0),
    }


def main():
    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    now = datetime.now(timezone.utc)
    try:
        # —— 0. 管理端登录 + 建省管理员 ——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("超管登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}
        hb_admin = AdminUser(
            username="verify_dash_admin", password_hash=hash_password("admin123"),
            name="看板验证省管", role="province_admin", province_code=HB_PROV,
        )
        db.add(hb_admin)
        db.flush()
        db.commit()
        HB = {"Authorization": "Bearer " + create_access_token({"admin_id": hb_admin.id})}

        # —— 基线快照 ——
        base_super = snap_summary(db, None)
        base_hb = snap_summary(db, HB_PROV)
        base_tr_s7 = snap_trends(db, None, 7)
        base_tr_s30 = snap_trends(db, None, 30)
        base_tr_hb7 = snap_trends(db, HB_PROV, 7)
        base_tr_hb30 = snap_trends(db, HB_PROV, 30)

        # —— 1. 词条 5 条（河北 3 + 北京 2；w_hb3 仅供领取未录制）——
        words = []
        for i, (code, prov, city, content) in enumerate([
            ("VFY-DASH-HB1", HB_PROV, HB_CITY, "看板河北词1"),
            ("VFY-DASH-HB2", HB_PROV, HB_CITY, "看板河北词2"),
            ("VFY-DASH-HB3", HB_PROV, HB_CITY, "看板河北词3"),
            ("VFY-DASH-BJ1", BJ_PROV, BJ_CITY, "看板北京词1"),
            ("VFY-DASH-BJ2", BJ_PROV, BJ_CITY, "看板北京词2"),
        ], 1):
            w = WordLibrary(code=code, dialect_point="测试点", content=content,
                            example_sentence="测试。", province_code=prov, city_code=city,
                            status="active")
            db.add(w)
            db.flush()
            words.append(w)
        db.commit()
        w_hb1, w_hb2, w_hb3, w_bj1, w_bj2 = words
        check("直写词条 5 条", all(w.id for w in words), f"ids={[w.id for w in words]}")

        # —— 2. 任务（河北 + 北京，均发布）——
        def make_task(name, prov, city, wid_list):
            t = TaskBatch(name=name, province_code=prov, city_code=city,
                          required_audio_count=30, claim_limit=10, status="published",
                          created_by=1)
            db.add(t)
            db.flush()
            for wid in wid_list:
                db.add(TaskBatchItem(task_batch_id=t.id, word_id=wid))
            return t

        task_hb = make_task("验证看板-河北", HB_PROV, HB_CITY, [w_hb1.id, w_hb2.id])
        task_bj = make_task("验证看板-北京", BJ_PROV, BJ_CITY, [w_bj1.id, w_bj2.id])
        db.commit()
        check("建任务并发布 x2", bool(task_hb.id and task_bj.id), f"hb={task_hb.id} bj={task_bj.id}")

        # —— 3. 发音人 3 人：sp_hb1(男18-30)/sp_hb2(女31-45)/sp_bj(女18-30) ——
        sp_hb1 = Speaker(device_id="verify_dash_hb1", nickname="看板河北甲",
                         province_code=HB_PROV, city_code=HB_CITY, team_code=HB_TEAM,
                         gender="male", age_bracket="age18_30", openid="vd_hb1")
        sp_hb2 = Speaker(device_id="verify_dash_hb2", nickname="看板河北乙",
                         province_code=HB_PROV, city_code=HB_CITY, team_code=HB_TEAM,
                         gender="female", age_bracket="age31_45", openid="vd_hb2")
        sp_bj = Speaker(device_id="verify_dash_bj1", nickname="看板北京甲",
                        province_code=BJ_PROV, city_code=BJ_CITY, team_code=BJ_TEAM,
                        gender="female", age_bracket="age18_30", openid="vd_bj1")
        db.add_all([sp_hb1, sp_hb2, sp_bj])
        db.flush()
        db.commit()
        # 控制建档时间顺序（sp_hb1 最早、sp_bj 最晚）
        for i, sp in enumerate([sp_hb1, sp_hb2, sp_bj]):
            sp.created_at = now - timedelta(days=3 - i)
        db.commit()
        check("建发音人 3 人", all(s.id for s in [sp_hb1, sp_hb2, sp_bj]))

        # —— 4. 直写录音 5 条（created_at 控制 last_active 顺序）——
        # sp_hb1: (hb,w1)approved1500 +10min | (hb,w2)pending2000 +10min  → 最新
        # sp_bj:  (bj,w1)approved3000 +1min  | (bj,w2)approved2000 +1min
        # sp_hb2: (hb,w1)rejected1000 +5min
        rows = [
            (sp_hb1, task_hb, w_hb1, "approved", 1500, now + timedelta(minutes=10)),
            (sp_hb1, task_hb, w_hb2, "pending", 2000, now + timedelta(minutes=10)),
            (sp_hb2, task_hb, w_hb1, "rejected", 1000, now + timedelta(minutes=5)),
            (sp_bj, task_bj, w_bj1, "approved", 3000, now + timedelta(minutes=1)),
            (sp_bj, task_bj, w_bj2, "approved", 2000, now + timedelta(minutes=1)),
        ]
        for sp, t, w, st, dur, ts in rows:
            db.add(Recording(task_id=t.id, word_id=w.id, speaker_id=sp.id,
                             audio_url="verify/dash.wav", audio_duration=dur, file_size=1000,
                             status=st, content_check_status="media_passed", created_at=ts))
        db.commit()
        check("直写录音 5 条", True)

        # —— 5. 领取记录：sp_hb1 领 hb1(已录)+hb3(未录) ——
        db.add(TaskClaim(task_id=task_hb.id, word_id=w_hb1.id, speaker_id=sp_hb1.id,
                         claimed_at=now - timedelta(days=1)))
        db.add(TaskClaim(task_id=task_hb.id, word_id=w_hb3.id, speaker_id=sp_hb1.id,
                         claimed_at=now - timedelta(hours=1)))
        db.commit()
        check("直写领取 2 条", True)

        # ================= summary =================
        r = c.get("/api/dashboard/summary", headers=SUPER)
        s = r.json()
        expect = base_super
        check("超管 summary 200", r.status_code == 200, str(r.status_code))
        check("summary 发音人总数 +3",
              s["speaker_total"] == expect["speaker_total"] + 3,
              f"{s['speaker_total']} vs {expect['speaker_total'] + 3}")
        check("summary 录音总数 +5",
              s["recording_total"] == sum(v[0] for v in expect["rec"].values()) + 5,
              f"{s['recording_total']}")
        check("summary 状态计数 +1pending/+3approved/+1rejected",
              s["pending"] == get(expect["rec"], "pending", (0, 0))[0] + 1
              and s["approved"] == get(expect["rec"], "approved", (0, 0))[0] + 3
              and s["rejected"] == get(expect["rec"], "rejected", (0, 0))[0] + 1,
              f"p={s['pending']} a={s['approved']} r={s['rejected']}")
        check("summary 总时长 +9500 / 有效时长 +6500",
              s["total_duration_ms"] == sum(v[1] for v in expect["rec"].values()) + 9500
              and s["approved_duration_ms"] == get(expect["rec"], "approved", (0, 0))[1] + 6500,
              f"total={s['total_duration_ms']} approved={s['approved_duration_ms']}")
        exp_rate = (get(expect["rec"], "approved", (0, 0))[0] + 3) / max(
            get(expect["rec"], "approved", (0, 0))[0] + 3 + get(expect["rec"], "rejected", (0, 0))[0] + 1, 1)
        check("summary 通过率 = approved/(approved+rejected)",
              abs(s["approval_rate"] - exp_rate) < 1e-9, f"{s['approval_rate']} vs {exp_rate}")
        check("summary 活跃任务 +2",
              s["active_task_total"] == expect["active_task"] + 2, f"{s['active_task_total']}")
        check("summary 团队数 +2",
              s["team_total"] == expect["team_total"] + 2, f"{s['team_total']}")
        check("summary 已录词条 +4（hb3 仅领取未录制）",
              s["distinct_word_total"] == expect["distinct_word"] + 4, f"{s['distinct_word_total']}")

        # —— summary 区域分布（超管按省）——
        reg13 = next((x for x in s["region_breakdown"] if x["code"] == HB_PROV), None)
        reg11 = next((x for x in s["region_breakdown"] if x["code"] == BJ_PROV), None)
        check("超管区域分布 河北+2人/+3录音",
              reg13 is not None
              and reg13["speaker_total"] == get(expect["region_sp"], HB_PROV, 0) + 2
              and reg13["recording_total"] == get(expect["region_rec"], HB_PROV, 0) + 3,
              f"河北 s={reg13 and reg13['speaker_total']} r={reg13 and reg13['recording_total']}")
        check("超管区域分布 北京+1人/+2录音",
              reg11 is not None
              and reg11["speaker_total"] == get(expect["region_sp"], BJ_PROV, 0) + 1
              and reg11["recording_total"] == get(expect["region_rec"], BJ_PROV, 0) + 2,
              f"北京 s={reg11 and reg11['speaker_total']} r={reg11 and reg11['recording_total']}")

        # —— summary 省管理员钳制（hebei_admin）——
        r = c.get("/api/dashboard/summary", headers=HB)
        sh = r.json()
        hb_ex = base_hb
        check("省管 summary 200", r.status_code == 200, str(r.status_code))
        check("省管 发音人 +2（排除北京）",
              sh["speaker_total"] == hb_ex["speaker_total"] + 2,
              f"{sh['speaker_total']} vs {hb_ex['speaker_total'] + 2}")
        check("省管 录音 +3（排除北京）",
              sh["recording_total"] == sum(v[0] for v in hb_ex["rec"].values()) + 3,
              f"{sh['recording_total']}")
        check("省管 有效时长 +1500（仅河北 approved）",
              sh["approved_duration_ms"] == get(hb_ex["rec"], "approved", (0, 0))[1] + 1500,
              f"{sh['approved_duration_ms']}")
        check("省管 活跃任务 +1",
              sh["active_task_total"] == hb_ex["active_task"] + 1, f"{sh['active_task_total']}")
        check("省管 已录词条 +2",
              sh["distinct_word_total"] == hb_ex["distinct_word"] + 2, f"{sh['distinct_word_total']}")
        hb_reg = {x["code"]: x for x in sh["region_breakdown"]}
        check("省管 区域分布不含北京且 1301 加量",
              BJ_PROV not in hb_reg
              and hb_reg.get(HB_CITY)
              and hb_reg[HB_CITY]["speaker_total"] == get(hb_ex["region_sp"], HB_CITY, 0) + 2
              and hb_reg[HB_CITY]["recording_total"] == get(hb_ex["region_rec"], HB_CITY, 0) + 3,
              f"1301 s={hb_reg.get(HB_CITY) and hb_reg[HB_CITY]['speaker_total']}")

        # ================= speakers =================
        def speaker_list(headers, **params):
            return c.get("/api/dashboard/speakers", headers=headers, params=params).json()

        # —— keyword 过滤：3 人全集 + 每行指标 ——
        r = c.get("/api/dashboard/speakers", headers=SUPER,
                  params={"keyword": "verify_dash", "page_size": 50})
        data = r.json()
        by_id = {x["id"]: x for x in data["items"]}
        check("speakers keyword=verify_dash → total=3",
              r.status_code == 200 and data["total"] == 3 and len(data["items"]) == 3,
              f"total={data.get('total')} len={len(data.get('items', []))}")
        hb1 = by_id[sp_hb1.id]
        hb2 = by_id[sp_hb2.id]
        bj = by_id[sp_bj.id]
        check("sp_hb1 行指标正确",
              hb1["recording_total"] == 2 and hb1["pending"] == 1 and hb1["approved"] == 1
              and hb1["rejected"] == 0 and hb1["total_duration_ms"] == 3500
              and hb1["approved_duration_ms"] == 1500 and abs(hb1["approval_rate"] - 1.0) < 1e-9
              and hb1["task_count"] == 1 and hb1["word_count"] == 2
              and hb1["team_code"] == HB_TEAM and hb1["gender"] == "male"
              and hb1["age_bracket"] == "age18_30" and hb1["nickname"] == "看板河北甲",
              f"{hb1}")
        check("sp_hb2 行指标正确",
              hb2["recording_total"] == 1 and hb2["approved"] == 0 and hb2["rejected"] == 1
              and hb2["total_duration_ms"] == 1000 and abs(hb2["approval_rate"] - 0.0) < 1e-9,
              f"{hb2}")
        check("sp_bj 行指标正确",
              bj["recording_total"] == 2 and bj["approved"] == 2
              and bj["total_duration_ms"] == 5000 and bj["word_count"] == 2,
              f"{bj}")
        # last_active 取最大录音时间（直接查库与接口同源，避免时区格式差异）
        max_ts = db.query(func.max(Recording.created_at)).filter(
            Recording.speaker_id == sp_hb1.id,
            Recording.task_id == task_hb.id,
        ).scalar()
        check("sp_hb1 last_active_at 正确",
              hb1["last_active_at"] == max_ts.isoformat(),
              f"{hb1['last_active_at']} vs {max_ts}")

        # —— 排序（相对顺序）——
        def order(params):
            d = speaker_list(SUPER, keyword="verify_dash", page_size=50, **params)
            idx = {x["id"]: i for i, x in enumerate(d["items"])}
            return idx

        idx = order({"sort_by": "recording"})
        check("sort=recording 相对顺序",
              idx[sp_bj.id] < idx[sp_hb1.id] < idx[sp_hb2.id],
              f"{idx}")
        idx = order({"sort_by": "approved"})
        check("sort=approved 相对顺序",
              idx[sp_bj.id] < idx[sp_hb1.id] < idx[sp_hb2.id],
              f"{idx}")
        idx = order({"sort_by": "duration"})
        check("sort=duration 相对顺序",
              idx[sp_bj.id] < idx[sp_hb1.id] < idx[sp_hb2.id],
              f"{idx}")
        idx = order({"sort_by": "last_active"})
        check("sort=last_active 相对顺序",
              idx[sp_hb1.id] < idx[sp_hb2.id] < idx[sp_bj.id],
              f"{idx}")
        idx = order({"sort_by": "created"})
        check("sort=created 相对顺序（新→旧：bj,hb2,hb1）",
              idx[sp_bj.id] < idx[sp_hb2.id] < idx[sp_hb1.id],
              f"{idx}")

        # —— 筛选：性别 / 年龄段 / 团队 ——
        d = speaker_list(SUPER, keyword="verify_dash", gender="male")
        check("筛选 gender=male → 1 人",
              d["total"] == 1 and d["items"][0]["id"] == sp_hb1.id, f"{d.get('total')}")
        d = speaker_list(SUPER, keyword="verify_dash", age_bracket="age31_45")
        check("筛选 age_bracket=age31_45 → 1 人",
              d["total"] == 1 and d["items"][0]["id"] == sp_hb2.id, f"{d.get('total')}")
        d = speaker_list(SUPER, keyword="verify_dash", team_code=BJ_TEAM)
        check("筛选 team_code=BJ → 1 人",
              d["total"] == 1 and d["items"][0]["id"] == sp_bj.id, f"{d.get('total')}")

        # —— 分页 ——
        d = speaker_list(SUPER, keyword="verify_dash", page=1, page_size=2)
        check("分页 page1/size2 → total=3, items=2",
              d["total"] == 3 and len(d["items"]) == 2, f"{d.get('total')} len={len(d.get('items', []))}")
        d = speaker_list(SUPER, keyword="verify_dash", page=2, page_size=2)
        check("分页 page2/size2 → items=1",
              d["total"] == 3 and len(d["items"]) == 1, f"len={len(d.get('items', []))}")

        # —— 非法筛选 422 ——
        r = c.get("/api/dashboard/speakers", headers=SUPER, params={"gender": "x", "sort_by": "bad"})
        check("非法 gender/sort_by → 422", r.status_code == 422, str(r.status_code))

        # —— 省管理员：仅本省发音人 ——
        d = speaker_list(HB, keyword="verify_dash")
        check("省管 speakers keyword → 仅河北 2 人",
              d["total"] == 2 and all(x["province_code"] == HB_PROV for x in d["items"]),
              f"total={d.get('total')} codes={[x['province_code'] for x in d.get('items', [])]}")

        # ================= claims =================
        r = c.get(f"/api/dashboard/speakers/{sp_hb1.id}/claims", headers=SUPER)
        cl = r.json()
        cmap = {x["word_id"]: x for x in cl}
        check("claims 返回 2 条", r.status_code == 200 and len(cl) == 2, str(r.status_code) + f" {len(cl)}")
        check("claims hb1 已录 / hb3 未录",
              cmap.get(w_hb1.id) and cmap[w_hb1.id]["recorded"] is True
              and cmap[w_hb1.id]["task_name"] == "验证看板-河北"
              and cmap[w_hb1.id]["word_content"] == "看板河北词1"
              and cmap.get(w_hb3.id) and cmap[w_hb3.id]["recorded"] is False
              and cmap[w_hb3.id]["word_content"] == "看板河北词3",
              f"{cl}")
        check("claims 领取时间降序（hb3 更新）",
              cl[0]["word_id"] == w_hb3.id, f"{[x['word_id'] for x in cl]}")

        # —— claims 权限 ——
        r = c.get(f"/api/dashboard/speakers/{sp_bj.id}/claims", headers=HB)
        check("省管看北京发音人 claims → 403", r.status_code == 403, str(r.status_code))
        r = c.get("/api/dashboard/speakers/999999/claims", headers=SUPER)
        check("不存在的发音人 claims → 404", r.status_code == 404, str(r.status_code))

        # ================= trends =================
        def trends(headers, days):
            return c.get("/api/dashboard/trends", headers=headers, params={"days": days}).json()

        t7 = trends(SUPER, 7)
        check("trends(7) 新增录音 +5",
              t7["new_recordings"] == base_tr_s7["total"] + 5, f"{t7['new_recordings']}")
        check("trends(7) 状态增量 +1pending/+3approved/+1rejected",
              t7["pending"] == base_tr_s7["pending"] + 1
              and t7["approved"] == base_tr_s7["approved"] + 3
              and t7["rejected"] == base_tr_s7["rejected"] + 1,
              f"p={t7['pending']} a={t7['approved']} r={t7['rejected']}")
        exp_rate = (base_tr_s7["approved"] + 3) / max(
            base_tr_s7["approved"] + 3 + base_tr_s7["rejected"] + 1, 1)
        check("trends(7) 通过率 = approved/(approved+rejected)",
              abs(t7["approval_rate"] - exp_rate) < 1e-9, f"{t7['approval_rate']} vs {exp_rate}")
        t30 = trends(SUPER, 30)
        check("trends(30) 新增录音 +5",
              t30["new_recordings"] == base_tr_s30["total"] + 5, f"{t30['new_recordings']}")
        thb = trends(HB, 7)
        check("省管 trends(7) 新增录音 +3（排除北京）",
              thb["new_recordings"] == base_tr_hb7["total"] + 3, f"{thb['new_recordings']}")
        check("省管 trends(7) 状态增量 +1pending/+1approved/+1rejected",
              thb["pending"] == base_tr_hb7["pending"] + 1
              and thb["approved"] == base_tr_hb7["approved"] + 1
              and thb["rejected"] == base_tr_hb7["rejected"] + 1,
              f"p={thb['pending']} a={thb['approved']} r={thb['rejected']}")
        r = c.get("/api/dashboard/trends", headers=SUPER, params={"days": 999})
        check("trends days 越界 → 422", r.status_code == 422, str(r.status_code))

        # ================= dashboard/words（词条采集难度） =================
        def word_map(headers, **params):
            d = c.get("/api/dashboard/words", headers=headers,
                      params={"page_size": 200, **params}).json()
            return {x["code"]: x for x in d["items"]}

        wmap = word_map(SUPER, sort_by="reject")
        check("dashboard/words 含种子词条",
              wmap.get("VFY-DASH-HB1") and wmap.get("VFY-DASH-BJ1"),
              f"codes={list(wmap)[:5]}")
        whb1 = wmap["VFY-DASH-HB1"]
        check("w_hb1 难度快照正确（录音2/通过1/驳回1/各率0.5）",
              whb1["recording_total"] == 2 and whb1["approved"] == 1 and whb1["rejected"] == 1
              and abs(whb1["approval_rate"] - 0.5) < 1e-9
              and abs(whb1["reject_rate"] - 0.5) < 1e-9
              and whb1["content"] == "看板河北词1" and whb1["dialect_point"] == "测试点",
              f"{whb1}")
        check("w_hb2 仅待审（1 条 pending）",
              wmap["VFY-DASH-HB2"]["recording_total"] == 1
              and wmap["VFY-DASH-HB2"]["pending"] == 1
              and wmap["VFY-DASH-HB2"]["rejected"] == 0,
              f"{wmap['VFY-DASH-HB2']}")
        check("w_hb3 无录音（仅被领取）",
              wmap["VFY-DASH-HB3"]["recording_total"] == 0
              and wmap["VFY-DASH-HB3"]["rejected"] == 0
              and wmap["VFY-DASH-HB3"]["approval_rate"] == 0.0,
              f"{wmap['VFY-DASH-HB3']}")
        check("w_bj1 全部通过",
              wmap["VFY-DASH-BJ1"]["recording_total"] == 1
              and wmap["VFY-DASH-BJ1"]["approved"] == 1
              and wmap["VFY-DASH-BJ1"]["rejected"] == 0,
              f"{wmap['VFY-DASH-BJ1']}")
        all_items = c.get("/api/dashboard/words", headers=SUPER,
                          params={"page_size": 200, "sort_by": "reject"}).json()["items"]
        seed_rank = [x["code"] for x in all_items if x["code"].startswith("VFY-DASH")]
        check("sort=reject 驳回多者在前（HB1 首个）",
              seed_rank[0] == "VFY-DASH-HB1", f"{seed_rank}")
        wmap_hb = word_map(HB, sort_by="reject")
        check("省管 dashboard/words 仅本省词条",
              {"VFY-DASH-HB1", "VFY-DASH-HB2", "VFY-DASH-HB3"} <= set(wmap_hb)
              and not any(k.startswith("VFY-DASH-BJ") for k in wmap_hb),
              f"codes={list(wmap_hb)}")
        r = c.get("/api/dashboard/words", headers=SUPER, params={"sort_by": "bad"})
        check("dashboard/words 非法 sort_by → 422", r.status_code == 422, str(r.status_code))

        # —— 未登录 401 ——
        r = c.get("/api/dashboard/summary")
        check("未登录 summary → 401", r.status_code == 401, str(r.status_code))

        cleanup(db)
        check("清理种子数据", True)
    finally:
        db.close()

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(results) + "\n")
    passed = sum(1 for x in results if x.startswith("[PASS]"))
    failed = sum(1 for x in results if x.startswith("[FAIL]"))
    print(f"RESULT: {passed} PASS / {failed} FAIL (详见 {OUT})")


def cleanup(db):
    sps = db.query(Speaker).filter(Speaker.device_id.like("verify_dash%")).all()
    sp_ids = [s.id for s in sps]
    if sp_ids:
        db.query(Recording).filter(Recording.speaker_id.in_(sp_ids)).delete()
        db.query(TaskClaim).filter(TaskClaim.speaker_id.in_(sp_ids)).delete()
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证看板-%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskClaim).filter(TaskClaim.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    for s in sps:
        db.delete(s)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFY-DASH%")).delete()
    db.query(AdminUser).filter(AdminUser.username == "verify_dash_admin").delete()
    db.commit()


if __name__ == "__main__":
    main()
