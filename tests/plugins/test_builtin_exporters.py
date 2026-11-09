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
