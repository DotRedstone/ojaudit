"""
Module: CLI End-to-end Tests
Description: 合成数据迁移、筛选、检测、打标和 CSV 榜单导出。
Scope: Test
"""

import csv
import json

from ojaudit.cli import main
from ojaudit.core.store import Store


def test_cli_end_to_end(tmp_path, capsys, monkeypatch):
    db = tmp_path / "test.sqlite"
    fixture = tmp_path / "old.json"
    fixture.write_text(
        json.dumps(
            {
                "contest": {
                    "platform": "synthetic",
                    "contest_id": "c1",
                    "name": "合成训练赛",
                },
                "participants": [
                    {"uid": "u1", "name": "甲"},
                    {"uid": "u2", "name": "乙"},
                    {"uid": "staff", "name": "管理者"},
                ],
                "submissions": [
                    {
                        "submission_id": f"s{i}",
                        "uid": uid,
                        "problem_index": 0,
                        "language": "cpp",
                        "verdict": "AC",
                        "score": 100,
                        "submit_time": i,
                        "phase": "contest",
                        "code": "int main(){return 123456789;}",
                    }
                    for i, uid in enumerate(["u1", "u2", "staff"], 1)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    base = ["--db", str(db)]
    main([*base, "migrate", str(fixture)])
    main([*base, "contests"])
    assert "合成训练赛" in capsys.readouterr().out
    main([*base, "hidden", "add", "--platform", "synthetic", "--uid", "staff"])
    main([*base, "analyze", "synthetic", "c1"])
    with Store(db) as store:
        run = store.execute("SELECT run_id FROM analysis_runs").fetchone()[0]
        findings = store.execute(
            "SELECT uid_a, uid_b FROM findings WHERE run_id=?", (run,)
        ).fetchall()
        assert [(r[0], r[1]) for r in findings] == [("u1", "u2")]
    main([*base, "mark", "synthetic", "c1", "u2", "cheater"])
    main([*base, "review", run, "u1", "u2", "0", "cpp", "已核查"])
    destination = tmp_path / "ranking.csv"
    main([*base, "export", "synthetic", "c1", "--output", str(destination)])
    with destination.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["UID"] for row in rows] == ["u1"]
    assert rows[0]["名次"] == "1"
    assert "标记" not in rows[0], "作弊者已除名、无人带标记时不输出标记列"
    with Store(db) as store:
        assert store.list_finding_reviews(run)[0]["status"] == "已核查"
