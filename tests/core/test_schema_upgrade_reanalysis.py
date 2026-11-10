"""
Module: Schema Upgrade and Reanalysis Tests
Description: 合成 v1 数据升级与重新分析后人工复核记录保留回归。
Scope: Test
Notes: 不使用真实用户或比赛数据。
"""

import sqlite3

from ojaudit.core.analysis import run_analysis
from ojaudit.core.reviews import annotate_review_staleness
from ojaudit.core.schema import SCHEMA_VERSION, Contest, Submission
from ojaudit.core.store import _MIGRATIONS, Store


def test_v1_database_upgrades_to_v2_without_losing_existing_data(tmp_path):
    path = tmp_path / "synthetic-v1.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(_MIGRATIONS[1])
        connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_version VALUES (1)")
        connection.execute("INSERT INTO platforms VALUES ('synthetic')")
        connection.execute(
            "INSERT INTO contests(platform, contest_id, name) VALUES (?, ?, ?)",
            ("synthetic", "c1", "合成训练赛"),
        )
        connection.execute(
            "INSERT INTO participants(platform, contest_id, uid, name) VALUES (?, ?, ?, ?)",
            ("synthetic", "c1", "u1", "虚构选手"),
        )
        connection.execute(
            """INSERT INTO person_marks(platform, contest_id, uid, mark, note, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("synthetic", "c1", "u1", "suspect", "原备注", "2026-01-01"),
        )
    with Store(path) as store:
        assert store.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        assert store.execute("SELECT name FROM contests").fetchone()[0] == "合成训练赛"
        assert store.execute("SELECT name FROM participants").fetchone()[0] == "虚构选手"
        assert store.list_person_marks("synthetic", "c1")[0]["note"] == "原备注"
        store.put_hidden_person("synthetic", "staff", "管理者")
        assert store.list_hidden_people()[0]["uid"] == "staff"
    with Store(path) as store:
        assert store.execute("SELECT count(*) FROM contests").fetchone()[0] == 1


def test_reanalysis_keeps_manual_records_and_marks_disappeared_findings_stale(tmp_path):
    code = "int main(){int value=1;return value+1;}"

    def submission(sid, uid, text, when):
        return Submission("synthetic", "c1", sid, uid, 0, "cpp", "AC", 100, when, "contest", text)

    path = tmp_path / "reanalyze.sqlite"
    with Store(path) as store:
        store.import_contest(
            Contest("synthetic", "c1", "合成训练赛"),
            submissions=[submission("s1", "u1", code, 1000), submission("s2", "u2", code, 2000)],
        )
        first = run_analysis(store, "synthetic", "c1", settings={})
        assert [row["pair"] for row in first.findings] == [["u1", "u2"]]
        store.put_finding_review(
            first.run_id, "u1", "u2", 0, "cpp", "需进一步核实", "保留的线索备注", "2026-01-01"
        )
        store.put_person_mark("synthetic", "c1", "u1", "suspect", "人工标记", "2026-01-01")
        store.put_submissions([submission("s2", "u2", "print('完全不同的代码')", 2000)])
        second = run_analysis(store, "synthetic", "c1", settings={})
        assert second.findings == ()
    with Store(path) as store:
        assert store.execute("SELECT count(*) FROM analysis_runs").fetchone()[0] == 2
        assert store.list_person_marks("synthetic", "c1")[0]["note"] == "人工标记"
        old_reviews = store.list_finding_reviews(first.run_id)
        assert old_reviews[0]["note"] == "保留的线索备注"
        assert annotate_review_staleness(old_reviews, [])[0]["is_stale"]
