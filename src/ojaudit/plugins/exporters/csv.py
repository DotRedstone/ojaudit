"""
Module: Exporter / csv
Description: 将确定性审查结果导出为 UTF-8 CSV。
Scope: Exporter
Notes: 对电子表格公式前缀进行转义，避免打开文件时执行公式。
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

_COLUMNS = ("problem", "language", "pair", "uid", "similarity", "level", "reason")


def _safe(value: object) -> str:
    text = " ↔ ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def export_csv(rows: Iterable[dict], destination: str | Path) -> Path:
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            str(row.get("problem", "")),
            str(row.get("language", "")),
            str(row.get("pair", row.get("uid", ""))),
        ),
    )
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=_COLUMNS, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for row in ordered:
            writer.writerow({key: _safe(row.get(key, "")) for key in _COLUMNS})
    return path
