"""任务级数据导出专项验证（进程内 TestClient）。

覆盖「点击任务名 → 任务详情页」的后端能力：
- GET /tasks/{id} 详情（word_count/recorded_count/approved_count/completion_status）
- GET /tasks/{id}/contributors 发音人贡献分页（计数 + 有效时长/无效时长 + 团队/属地名，
  发音人ID 升序；summary 反映全任务；keyword/team_code 筛选；分页）
- GET /tasks/{id}/export 导出 CSV（utf-8-sig BOM、列头、行值）
- 省管理员访问他省任务 403；不存在任务 404

用法: ./.venv/Scripts/python.exe scripts/verify_task_contributors.py
"""
import csv
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.recording import Recording  # noqa: E402
from app.models.speaker import Speaker  # noqa: E402
from app.models.task import TaskBatch, TaskBatchItem  # noqa: E402
from app.models.task_claim import TaskClaim  # noqa: E402
from app.models.team_code import TeamCode  # noqa: E402
from app.models.word import WordLibrary  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "_verify_task_contributors.txt")
results = []
TEAM = "VFTK-01"
PROV, CITY, DISTRICT = "11", "1101", "110101"  # 北京市东城区，无真实团队码不冲突


def check(name, ok, extra=""):
    results.append(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        results.append("    >>> 上述项未通过，请检查")


def cleanup(db):
    for sp in db.query(Speaker).filter(Speaker.device_id.like("vftk_%")).all():
        db.query(Recording).filter(Recording.speaker_id == sp.id).delete()
        db.query(TaskClaim).filter(TaskClaim.speaker_id == sp.id).delete()
        db.delete(sp)
    for t in db.query(TaskBatch).filter(TaskBatch.name.like("验证任务贡献%")).all():
        db.query(Recording).filter(Recording.task_id == t.id).delete()
        db.query(TaskClaim).filter(TaskClaim.task_id == t.id).delete()
        db.query(TaskBatchItem).filter(TaskBatchItem.task_batch_id == t.id).delete()
        db.delete(t)
    db.query(WordLibrary).filter(WordLibrary.code.like("VFTK-%")).delete()
    db.query(TeamCode).filter(TeamCode.code == TEAM).delete()
    db.commit()


def main():
    c = TestClient(app)
    db = SessionLocal()
    cleanup(db)
    try:
        # —— 0. 管理端登录 ——
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        check("超管登录", r.status_code == 200, str(r.status_code))
        SUPER = {"Authorization": "Bearer " + r.json()["access_token"]}
        r = c.post("/api/auth/login", json={"username": "hebei_admin", "password": "admin123"})
        check("省管登录(河北)", r.status_code == 200, str(r.status_code))
        HB = {"Authorization": "Bearer " + r.json()["access_token"]}

        # —— 1. 建团队码 / 4 词条 / 任务发布 ——
        r = c.post("/api/team-codes", headers=SUPER,
                   json={"code": TEAM, "name": "验证任务贡献团队", "province_code": PROV,
                         "city_code": CITY, "district_code": DISTRICT})
        check("建团队码 VFTK-01", r.status_code == 200, str(r.status_code) + " " + str(r.json()))
        words = []
        for i in range(4):
            w = WordLibrary(code=f"VFTK-W{i+1}", dialect_point="北京话", content=f"任务贡献词{i+1}",
                            example_sentence="测试。", province_code=PROV, status="active")
            db.add(w)
            db.flush()
            words.append(w)
        db.commit()
        r = c.post("/api/tasks", headers=SUPER, json={
            "name": "验证任务贡献", "description": "任务级导出验证",
            "province_code": PROV, "city_code": CITY, "team_code": TEAM,
            "required_audio_count": 30, "word_ids": [w.id for w in words]})
        task_id = r.json().get("id") if r.status_code == 200 else None
        check("建任务", r.status_code == 200 and task_id, str(r.status_code) + " " + str(r.json()))
        r = c.post(f"/api/tasks/{task_id}/publish", headers=SUPER)
        check("发布任务", r.status_code == 200 and r.json().get("status") == "published",
              str(r.status_code) + " " + str(r.json()))

        # —— 2. 发音人 A(绑团队) / B(无团队)，直写录音 ——
        sp_a = Speaker(device_id="vftk_a", nickname="任务贡献甲", team_code=TEAM,
                       province_code=PROV, city_code=CITY, district_code=DISTRICT)
        sp_b = Speaker(device_id="vftk_b", nickname="任务贡献乙",
                       province_code=PROV, city_code=CITY, district_code=DISTRICT)
        db.add(sp_a)
        db.add(sp_b)
        db.flush()
        a_id, b_id = sp_a.id, sp_b.id
        db.commit()

        def rec(sp, word, status, dur_ms):
            db.add(Recording(task_id=task_id, word_id=word.id, speaker_id=sp.id,
                             audio_url=f"media/verify_task_{task_id}_{word.id}_{sp.id}.wav",
                             audio_duration=dur_ms, file_size=100, status=status))
            db.flush()

        # A：pending 1000 + approved 2000 + rejected 3000 → 3条 有效2000 无效3000
        rec(sp_a, words[0], "pending", 1000)
        rec(sp_a, words[0], "approved", 2000)
        rec(sp_a, words[1], "rejected", 3000)
        # B：approved 4000 + pending 5000 → 2条 有效4000
        rec(sp_b, words[2], "approved", 4000)
        rec(sp_b, words[2], "pending", 5000)
        db.commit()

        # —— 3. 任务详情 ——
        r = c.get(f"/api/tasks/{task_id}", headers=SUPER)
        d = r.json()
        check("任务详情 200 + 进度字段",
              r.status_code == 200 and d.get("word_count") == 4
              and d.get("recorded_count") == 3 and d.get("approved_count") == 2
              and d.get("name") == "验证任务贡献",
              str(r.status_code) + f" word={d.get('word_count')} rec={d.get('recorded_count')} appr={d.get('approved_count')}")

        # —— 4. 发音人贡献列表 ——
        r = c.get(f"/api/tasks/{task_id}/contributors", headers=SUPER)
        body = r.json()
        items = body.get("items", [])
        sm = body.get("summary", {})
        check("contributors 200 + total=2",
              r.status_code == 200 and body.get("total") == 2, str(r.status_code) + " " + str(body)[:120])
        check("summary 全任务聚合",
              sm.get("speaker_count") == 2 and sm.get("recording_total") == 5
              and sm.get("approved_total") == 2 and sm.get("valid_duration_ms") == 6000,
              str(sm))
        check("列表按发音人ID升序",
              [x["speaker_id"] for x in items] == sorted([a_id, b_id]),
              str([x["speaker_id"] for x in items]))
        row_a = next(x for x in items if x["speaker_id"] == a_id)
        row_b = next(x for x in items if x["speaker_id"] == b_id)
        check("A 行计数+时长+团队",
              row_a["recording_total"] == 3 and row_a["pending"] == 1
              and row_a["approved"] == 1 and row_a["rejected"] == 1
              and row_a["valid_duration_ms"] == 2000 and row_a["invalid_duration_ms"] == 3000
              and row_a["total_duration_ms"] == 6000
              and row_a["approval_rate"] == 0.5
              and row_a["team_code"] == TEAM and row_a["team_name"] == "验证任务贡献团队"
              and row_a["province_name"] == "北京市" and row_a["city_name"] == "市辖区"
              and row_a["district_name"] == "东城区",
              str(row_a))
        check("B 行计数+时长+无团队",
              row_b["recording_total"] == 2 and row_b["approved"] == 1
              and row_b["pending"] == 1 and row_b["rejected"] == 0
              and row_b["valid_duration_ms"] == 4000 and row_b["approval_rate"] == 1.0
              and row_b["team_code"] == "",
              str(row_b))

        # —— 5. 筛选 / 分页 ——
        r = c.get(f"/api/tasks/{task_id}/contributors", headers=SUPER, params={"keyword": "乙"})
        ids = {x["speaker_id"] for x in r.json().get("items", [])}
        check("keyword=乙 → 只有 B", r.json()["total"] == 1 and ids == {b_id}, f"{sorted(ids)}")
        r = c.get(f"/api/tasks/{task_id}/contributors", headers=SUPER, params={"keyword": "vftk_a"})
        ids = {x["speaker_id"] for x in r.json().get("items", [])}
        check("keyword=设备ID vftk_a → 只有 A", r.json()["total"] == 1 and ids == {a_id}, f"{sorted(ids)}")
        r = c.get(f"/api/tasks/{task_id}/contributors", headers=SUPER, params={"team_code": TEAM})
        ids = {x["speaker_id"] for x in r.json().get("items", [])}
        check("team_code=VFTK-01 → 只有 A", r.json()["total"] == 1 and ids == {a_id}, f"{sorted(ids)}")
        r = c.get(f"/api/tasks/{task_id}/contributors", headers=SUPER, params={"page": 1, "page_size": 1})
        check("分页 page_size=1 → 1 条 + total=2",
              r.status_code == 200 and len(r.json()["items"]) == 1 and r.json()["total"] == 2,
              f"len={len(r.json().get('items', []))} total={r.json().get('total')}")

        # —— 6. 导出 CSV ——
        r = c.get(f"/api/tasks/{task_id}/export", headers=SUPER)
        ok_ctype = r.status_code == 200 and "text/csv" in r.headers.get("Content-Type", "")
        ok_bom = r.content.startswith(b"\xef\xbb\xbf")
        text = r.content.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        header_ok = (r.status_code == 200 and rows
                     and list(rows[0].keys()) == [
                         "发音人ID", "昵称", "设备ID", "团队码", "团队名", "省份", "城市", "区县",
                         "录音总数", "待审核数", "通过数", "驳回数",
                         "总时长_ms", "有效时长_ms", "无效时长_ms", "通过率", "最近提交时间"])
        row_a_csv = next((x for x in rows if x["发音人ID"] == str(a_id)), None)
        csv_a_ok = (row_a_csv is not None
                    and row_a_csv["昵称"] == "任务贡献甲"
                    and row_a_csv["团队码"] == TEAM and row_a_csv["团队名"] == "验证任务贡献团队"
                    and row_a_csv["录音总数"] == "3" and row_a_csv["通过数"] == "1"
                    and row_a_csv["有效时长_ms"] == "2000" and row_a_csv["通过率"] == "0.5")
        check("导出 CSV（text/csv + BOM + 列头）",
              ok_ctype and ok_bom and header_ok and len(rows) == 2,
              f"ctype={r.headers.get('Content-Type')} bom={ok_bom} rows={len(rows)}")
        check("导出 CSV A 行值", csv_a_ok, str(row_a_csv))

        # —— 7. 权限 / 404 ——
        r = c.get(f"/api/tasks/{task_id}", headers=HB)
        check("省管(河北)访问北京任务详情 → 403", r.status_code == 403, str(r.status_code))
        r = c.get(f"/api/tasks/{task_id}/contributors", headers=HB)
        check("省管访问 contributors → 403", r.status_code == 403, str(r.status_code))
        r = c.get(f"/api/tasks/{task_id}/export", headers=HB)
        check("省管访问 export → 403", r.status_code == 403, str(r.status_code))
        r = c.get("/api/tasks/999999", headers=SUPER)
        check("不存在任务详情 → 404", r.status_code == 404, str(r.status_code))

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
