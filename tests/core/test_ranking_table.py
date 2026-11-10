"""
Module: Test / core ranking table
Description: 导出表格的可选列（各题得分、提交次数、用时）、标记列的取舍与各格式写出。
Scope: Test
Notes: 只使用合成选手与提交。
"""

from __future__ import annotations

import csv

from ojaudit.core.ranking import RankingOptions, build_final_ranking, derive_rows
from ojaudit.core.ranking_table import TableOptions, build_table, problem_label, write_table

START = 1_700_000_000_000


def _ranking(marks=None, options=None):
    rows = derive_rows(
        "p",
        [("u1", "甲"), ("u2", "乙")],
        [
            ("u1", 0, 0, START + 60_000, "contest"),
            ("u1", 0, 100, START + 600_000, "contest"),
            ("u1", 1, 50, START + 3_723_000, "contest"),
            ("u2", 1, 100, START + 120_000, "contest"),
            ("u2", 2, 100, START + 999_000, "practice"),
        ],
    )
    return build_final_ranking(rows, marks or {}, options=options or RankingOptions())


def test_default_table_has_no_mark_column():
    table = build_table(_ranking(), [0, 1, 2])
    assert table.headers == ("名次", "姓名", "UID", "总分")
    assert table.rows[0] == (1, "甲", "u1", 150)


def test_per_problem_attempts_and_times():
    table = build_table(_ranking(), [0, 1, 2], TableOptions(True, True, True), START)
    assert table.headers[3:6] == ("A", "A 提交", "A 用时")
    assert table.headers[-1] == "总分"
    first = dict(zip(table.headers, table.rows[0]))
    assert (first["A"], first["A 提交"], first["A 用时"]) == (100, 2, "0:10:00")
    assert first["B 用时"] == "1:02:03"
    assert first["C"] == "" and first["C 提交"] == "", "赛后提交不计入"


def test_totals_without_per_problem_and_mark_column():
    marked = _ranking({"u2": "cheater"}, RankingOptions(cheaters="mark"))
    table = build_table(marked, [0, 1], TableOptions(attempts=True, times=True), START)
    assert table.headers == ("名次", "姓名", "UID", "标记", "总分", "提交", "最后得分")
    assert dict(zip(table.headers, table.rows[0]))["提交"] == 3
    assert dict(zip(table.headers, table.rows[0]))["最后得分"] == "1:02:03"
    assert table.rows[1][3] == "作弊"


def test_writers_share_headers(tmp_path):
    table = build_table(_ranking(), [0, 1], TableOptions(per_problem=True))
    with write_table(table, "csv", tmp_path / "r.csv").open(encoding="utf-8-sig") as stream:
        assert next(csv.reader(stream)) == list(table.headers)
    assert "| 名次 | 姓名 | UID | A | B | 总分 |" in write_table(
        table, "md", tmp_path / "r.md"
    ).read_text(encoding="utf-8")
    page = write_table(table, "html", tmp_path / "r.html").read_text(encoding="utf-8")
    assert "<th" in page and "甲" in page


def test_problem_labels():
    assert [problem_label(i) for i in (0, 25, 26, 27)] == ["A", "Z", "AA", "AB"]
