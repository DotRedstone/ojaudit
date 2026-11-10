"""
Module: Store Tests
Description: 验证 SQLite 初始化、迁移、比赛写入与管理/复核记录持久化。
Scope: Test
"""

import pytest

from ojaudit.core.schema import (
    Contest,
    Participant,
    Problem,
    Submission,
    language_bucket,
    parse_problem_index,
)
from ojaudit.core.store import Store


def test_store_migrates_and_persists_contest(tmp_path):
    path = tmp_path / "db" / "test.sqlite"
    with Store(path) as store:
        store.put_contest("demo", "c1", "合成训练赛")
        row = store.execute(
            "SELECT name FROM contests WHERE platform=? AND contest_id=?",
            ("demo", "c1"),
        ).fetchone()
        assert row["name"] == "合成训练赛"
        assert store.execute("SELECT version FROM schema_version").fetchone()[0] == 2


def _submission(sid, uid="u1", contest="c1", index=0):
    return Submission("demo", contest, sid, uid, index, "cpp", "AC", 100, 1, "contest", "x")


def test_failed_import_rolls_back_everything(tmp_path):
    with Store(tmp_path / "s.sqlite") as store:
        bad = _submission("s2", contest="other")
        with pytest.raises(ValueError):
            store.import_contest(Contest("demo", "c1", "合成"), (), (), [_submission("s1"), bad])
        assert store.list_contests() == []
        with pytest.raises(RuntimeError), store.transaction():
            store.put_contest("demo", "c2", "合成")
            with store.transaction():
                store.put_participants([Participant("demo", "c2", "u1", "甲")])
            raise RuntimeError("中途失败")
        assert store.list_contests() == []
        assert store.execute("SELECT count(*) FROM participants").fetchone()[0] == 0


def test_import_contest_fills_people_and_keeps_real_titles(tmp_path):
    with Store(tmp_path / "s.sqlite") as store:
        contest = Contest("demo", "c1", "合成", start_time=1_700_000_000_000)
        store.import_contest(
            contest,
            [Participant("demo", "c1", "u1", "甲")],
            [Problem("demo", "c1", 0, "P0", "加法")],
            [_submission("s1"), _submission("s2", uid="u2")],
        )
        store.put_problems([Problem("demo", "c1", 0, "0", "题 0")])
        names = dict(store.execute("SELECT uid, name FROM participants").fetchall())
        assert names == {"u1": "甲", "u2": "u2"}
        assert store.execute("SELECT title FROM problems").fetchone()[0] == "加法"
        assert store.list_contests()[0].start_time == 1_700_000_000_000
        assert [s.submission_id for s in store.submissions("demo", "c1")] == ["s1", "s2"]


def test_save_analysis_orders_pair(tmp_path):
    with Store(tmp_path / "s.sqlite") as store:
        store.save_analysis(
            "r1",
            "demo",
            "c1",
            "x",
            "test",
            "2026-01-01",
            [{"uid_a": "b", "uid_b": "a", "problem_index": 0, "language": "cpp", "level": "存疑"}],
        )
        row = store.execute("SELECT uid_a, uid_b, verdict_level FROM findings").fetchone()
        assert tuple(row) == ("a", "b", "存疑")


def test_problem_index_and_language_normalization():
    assert [parse_problem_index(v) for v in ("A", "c", "Z", "AA", "3", " 12 ")] == [
        0,
        2,
        25,
        26,
        3,
        12,
    ]
    for bad in ("", "A1", "题"):
        with pytest.raises(ValueError):
            parse_problem_index(bad)
    assert language_bucket("GNU G++17") == "cpp"
    assert language_bucket("PyPy3") == "python"
    assert language_bucket("JavaScript") == "other"
    assert language_bucket("Java 21") == "java"


def test_accepted_verdicts():
    from ojaudit.core.schema import is_accepted

    for verdict in ("AC", "Accepted", "accepted", "答案正确", "通过"):
        assert is_accepted(verdict), verdict
    for verdict in ("WA", "未通过", "部分通过", "答案错误", "", "Wrong Answer"):
        assert not is_accepted(verdict), verdict
