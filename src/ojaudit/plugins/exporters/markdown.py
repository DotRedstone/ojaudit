"""
Module: Exporter / markdown
Description: 将确定性审查结果导出为 Markdown 表格。
Scope: Exporter
Notes: 导出只写调用方指定路径，不读取数据库或访问网络。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def export_markdown(rows: Iterable[dict], destination: str | Path) -> Path:
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            str(row.get("problem", "")),
            str(row.get("language", "")),
            str(row.get("pair", row.get("uid", ""))),
        ),
    )
    columns = (
        ("rank", "uid", "name", "score", "person_mark")
        if ordered and "rank" in ordered[0]
        else ("problem", "language", "pair", "uid", "similarity", "level", "reason")
    )
    if columns[0] == "rank":
        ordered.sort(key=lambda row: (int(row["rank"]), str(row.get("uid", ""))))
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in ordered:
        values = []
        for key in columns:
            value = row.get(key, "")
            if isinstance(value, (list, tuple)):
                value = " ↔ ".join(map(str, value))
            values.append(_cell(value))
        lines.append("| " + " | ".join(values) + " |")
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
