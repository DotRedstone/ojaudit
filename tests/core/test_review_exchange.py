"""
Module: Test / core review exchange
Description: 复核结果导出、合并导入（取更重结论、备注合并、冲突报告）、未分析比赛的复核延后生效与 CLI。
Scope: Test
Notes: 只使用合成比赛、选手与线索。
"""

from __future__ import annotations

import json

import pytest

from ojaudit.cli import main
from ojaudit.core.review_exchange import (
    export_reviews,
    import_reviews,
    read_reviews,
    write_reviews,
)
from ojaudit.core.schema import Contest, Participant
from ojaudit.core.store import Store


def _store(path, *, analyzed=True):
    store = Store(path)
    store.import_contest(
        Contest("nowcoder", "1", "合成赛"),
        [Participant("nowcoder", "1", uid, uid.upper()) for uid in ("a", "b", "c")],
    )
    if analyzed:
        store.save_analysis(
            "run1",
            "nowcoder",
            "1",
            "x",
            "test",
            "2026-01-01",
            [{"uid_a": "a", "uid_b": "b", "problem_index": 0, "language": "cpp", "level": "存疑"}],
        )
    return store


def test_export_then_merge_takes_stronger_and_reports_conflicts(tmp_path):
    with _store(tmp_path / "mine.sqlite") as mine:
        mine.put_person_mark("nowcoder", "1", "a", "normal", "我看过", "t")
        mine.put_finding_review("run1", "a", "b", 0, "cpp", "无需跟进", "", "t")
    with _store(tmp_path / "theirs.sqlite") as theirs:
        theirs.put_person_mark("nowcoder", "1", "a", "cheater", "和 B 一模一样", "t")
        theirs.put_person_mark("nowcoder", "1", "c", "suspect", "", "t")
        theirs.put_finding_review("run1", "b", "a", 0, "cpp", "已核查", "", "t")
        theirs.put_hidden_person("nowcoder", "m", "老师")
        path = write_reviews(export_reviews(theirs), tmp_path / "theirs.json")
    data = read_reviews(path)
    assert data["contests"][0]["people"][0]["name"] == "A"
    with Store(tmp_path / "mine.sqlite") as mine:
        report = import_reviews(mine, data, "theirs.json")
        marks = {row["uid"]: row for row in mine.list_person_marks("nowcoder", "1")}
        assert marks["a"]["mark"] == "cheater", "取更重的结论"
        assert marks["a"]["note"] == "我看过；和 B 一模一样（theirs.json）"
        assert marks["c"]["mark"] == "suspect"
        assert mine.list_contest_reviews("nowcoder", "1")[0]["status"] == "已核查"
        assert [row["uid"] for row in mine.list_hidden_people()] == ["m"]
    assert (report.marks_added, report.marks_raised) == (1, 1)
    assert (report.reviews_added, report.reviews_raised) == (0, 1)
    assert len(report.conflicts) == 2 and report.conflicts[0][2:] == ("正常", "作弊", "作弊")
    # 再导入一次不重复叠加备注，也不再算加重。
    with Store(tmp_path / "mine.sqlite") as mine:
        again = import_reviews(mine, data, "theirs.json")
        note = mine.list_person_marks("nowcoder", "1")[0]["note"]
    assert (again.marks_added, again.marks_raised, again.reviews_raised) == (0, 0, 0)
    assert note.count("和 B 一模一样") == 1


def test_weaker_import_keeps_local_and_unanalyzed_contest_is_registered(tmp_path):
    with _store(tmp_path / "mine.sqlite") as mine:
        mine.put_person_mark("nowcoder", "1", "a", "cheater", "", "t")
    data = {
        "format": "ojaudit-reviews",
        "version": 1,
        "contests": [
            {
                "platform": "nowcoder",
                "contest_id": "1",
                "people": [{"uid": "a", "mark": "normal", "note": ""}],
            },
            {
                "platform": "nowcoder",
                "contest_id": "9",
                "name": "别人排查的比赛",
                "people": [{"uid": "x", "name": "某人", "mark": "cheater", "note": ""}],
                "findings": [
                    {"uid_a": "x", "uid_b": "y", "problem_index": 1, "language": "cpp",
                     "status": "已核查", "note": ""}
                ],
            },
        ],
    }  # fmt: skip
    with Store(tmp_path / "mine.sqlite") as mine:
        report = import_reviews(mine, data)
        assert mine.list_person_marks("nowcoder", "1")[0]["mark"] == "cheater", "不降级"
        assert mine.contest_exists("nowcoder", "9"), "登记为未采集"
        assert mine.list_person_marks("nowcoder", "9")[0]["mark"] == "cheater"
        assert mine.list_contest_reviews("nowcoder", "9")[0]["status"] == "已核查"
    assert report.contests_added == 1 and report.conflicts[0][4] == "作弊"


def test_invalid_files_are_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": "other"}), encoding="utf-8")
    with pytest.raises(ValueError, match="不是 ojaudit"):
        read_reviews(bad)
    bad.write_text(
        json.dumps(
            {
                "format": "ojaudit-reviews",
                "version": 1,
                "contests": [{"platform": "p", "contest_id": "1", "people": [{"uid": "a"}]}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="人员结论无效"):
        read_reviews(bad)


def test_cli_reviews_export_import(tmp_path, capsys):
    source, target = tmp_path / "s.sqlite", tmp_path / "t.sqlite"
    with _store(source) as store:
        store.put_person_mark("nowcoder", "1", "b", "cheater", "", "t")
    with _store(target):
        pass
    out = tmp_path / "r.json"
    main(["--db", str(source), "reviews", "export", str(out), "--contest", "nowcoder/1"])
    main(["--db", str(target), "reviews", "import", str(out)])
    assert "人员结论新增 1" in capsys.readouterr().out
    with Store(target) as store:
        assert store.list_person_marks("nowcoder", "1")[0]["uid"] == "b"
