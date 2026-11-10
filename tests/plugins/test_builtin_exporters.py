"""
Module: Builtin Exporter Tests
Description: 验证 Markdown、CSV 与 HTML 导出顺序稳定及不可信字段转义。
Scope: Test
"""

import csv

from ojaudit.plugins.exporters.csv import export_csv
from ojaudit.plugins.exporters.html import export_html
from ojaudit.plugins.exporters.markdown import export_markdown


def test_exporters_are_deterministic_and_escape_untrusted_cells(tmp_path):
    rows = [
        {
            "problem": 2,
            "pair": ["u2", "u3"],
            "reason": "=1+1",
            "level": "中",
            "scores": {"L1": 0.9, "L2": 1.0},
            "timeline": {"who_first": "A", "delta_seconds": 12.0},
            "code_a": "<script>alert(1)</script>",
            "code_b": "int main() {}",
        },
        {"problem": 1, "pair": ["u1", "u2"], "reason": "包含 | 分隔符", "level": "高"},
    ]
    md1 = export_markdown(rows, tmp_path / "one.md").read_text(encoding="utf-8")
    md2 = export_markdown(list(reversed(rows)), tmp_path / "two.md").read_text(encoding="utf-8")
    assert md1 == md2
    assert "包含 \\| 分隔符" in md1

    csv_path = export_csv(rows, tmp_path / "result.csv")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        exported = list(csv.DictReader(stream))
    assert exported[0]["problem"] == "1"
    assert exported[1]["reason"] == "'=1+1"

    html_one = export_html(rows, tmp_path / "one.html").read_bytes()
    html_two = export_html(list(reversed(rows)), tmp_path / "two.html").read_bytes()
    assert html_one == html_two
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_one.decode("utf-8")
    assert "时间线" in html_one.decode("utf-8")
    assert "代码 A" in html_one.decode("utf-8")


def test_xlsx_ranking_marks_or_drops_cheaters(tmp_path):
    from openpyxl import load_workbook

    from ojaudit.core.ranking import RankingOptions, build_final_ranking
    from ojaudit.core.ranking_table import build_table
    from ojaudit.plugins.exporters.xlsx import export_xlsx

    rows = [
        {"platform": "p", "uid": "u1", "name": "甲", "score": 300, "rank": 1},
        {"platform": "p", "uid": "u2", "name": "=SUM(A1)", "score": 200, "rank": 2},
        {"platform": "p", "uid": "u3", "name": "丙", "score": 100, "rank": 3},
    ]
    marked = build_final_ranking(rows, {"u1": "cheater"}, options=RankingOptions(cheaters="mark"))
    sheet = load_workbook(export_xlsx(build_table(marked), tmp_path / "mark.xlsx")).active
    assert [c.value for c in sheet[1]] == ["名次", "姓名", "UID", "标记", "总分"]
    assert [c.value for c in sheet[2]] == [1, "甲", "u1", "作弊", 300]
    assert sheet["A2"].fill.fgColor.rgb.endswith("F8D7DA")
    assert sheet["B3"].data_type == "s", "文本不会被当作公式"
    dropped = build_final_ranking(rows, {"u1": "cheater"}, options=RankingOptions(cheaters="drop"))
    sheet = load_workbook(export_xlsx(build_table(dropped), tmp_path / "drop.xlsx")).active
    assert [c.value for c in sheet[1]] == ["名次", "姓名", "UID", "总分"], "无标记时没有标记列"
    assert [row[1].value for row in sheet.iter_rows(min_row=2)] == ["=SUM(A1)", "丙"]
    assert [row[0].value for row in sheet.iter_rows(min_row=2)] == [1, 2], "除名后重新编号"
