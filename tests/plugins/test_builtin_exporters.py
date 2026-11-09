"""
Module: Builtin Exporter Tests
Description: 验证 Markdown 与 CSV 导出顺序稳定及公式前缀转义。
Scope: Test
"""

import csv

from ojaudit.plugins.exporters.csv import export_csv
from ojaudit.plugins.exporters.markdown import export_markdown


def test_exporters_are_deterministic_and_escape_untrusted_cells(tmp_path):
    rows = [
        {"problem": 2, "pair": ["u2", "u3"], "reason": "=1+1", "level": "中"},
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
