"""
Module: Core / ranking table
Description: 把最终排名排成导出用的表格（可选各题得分、提交次数、时间列），并写成 Markdown / CSV / HTML；
    Excel 由 xlsx 导出器写出。
Scope: Core
Notes:
- 「名单处理」（作弊者、存疑者、管理者、未提交者）由 core.ranking 决定；本模块只决定表格展示哪些列。
- 没有任何人带标记时不输出标记列。
- 文本写入 CSV / Excel 时防公式注入；HTML 全部转义。
"""

from __future__ import annotations

import csv
import html
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ojaudit.core.ranking import FinalRanking

MARK_NAMES = {"cheater": "作弊", "suspect": "存疑", "manager": "管理者"}


@dataclass(frozen=True, slots=True)
class TableOptions:
    per_problem: bool = False  # 各题得分列
    attempts: bool = False  # 提交次数（开各题时每题一列，否则一列总数）
    times: bool = False  # 时间（开各题时每题得分用时，否则最后得分用时）


@dataclass(frozen=True, slots=True)
class RankingTable:
    headers: tuple[str, ...]
    # 每列的类型：int / num / text；导出器据此决定对齐与是否按文本保存。
    kinds: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    marks: tuple[str, ...]
    title: str = "排行榜"

    @property
    def mark_column(self) -> int | None:
        return self.headers.index("标记") if "标记" in self.headers else None


def problem_label(index: int) -> str:
    """题号 0,1,2… 显示为 A,B,C…，超过 26 题时为 AA、AB…。"""
    label = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        label = chr(65 + rest) + label
    return label


def format_time(timestamp: int, start: int | None) -> str:
    """有比赛开始时间时显示用时 H:MM:SS，否则显示提交时刻；没有时间为空。"""
    if not timestamp:
        return ""
    if start and timestamp >= start:
        seconds = (timestamp - start) // 1000
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    if timestamp >= 10**11:
        from datetime import datetime

        return datetime.fromtimestamp(timestamp / 1000).astimezone().strftime("%m-%d %H:%M:%S")
    return str(timestamp)


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def build_table(
    ranking: FinalRanking,
    problems: Iterable[int] = (),
    options: TableOptions | None = None,
    start_time: int | None = None,
    title: str = "排行榜",
) -> RankingTable:
    table = options or TableOptions()
    rows = list(ranking.rows)
    indices = sorted(set(problems) | {int(p) for row in rows for p in (row.get("problems") or {})})
    marks = tuple(str(row.get("person_mark", "") or "") for row in rows)
    headers: list[str] = ["名次", "姓名", "UID"]
    kinds: list[str] = ["int", "text", "text"]
    # 标记紧跟身份列，列很多时也不会被挤到最右边看不见。
    if any(marks):
        headers.append("标记")
        kinds.append("text")
    if table.per_problem:
        for index in indices:
            label = problem_label(index)
            headers.append(label)
            kinds.append("num")
            if table.attempts:
                headers.append(f"{label} 提交")
                kinds.append("int")
            if table.times:
                headers.append(f"{label} 用时")
                kinds.append("text")
    headers.append("总分")
    kinds.append("num")
    if not table.per_problem:
        if table.attempts:
            headers.append("提交")
            kinds.append("int")
        if table.times:
            headers.append("最后得分")
            kinds.append("text")
    body = []
    for row, mark in zip(rows, marks):
        detail = row.get("problems") or {}
        cells: list[Any] = [int(row.get("rank", 0)), str(row.get("name", "")), str(row["uid"])]
        if any(marks):
            cells.append(MARK_NAMES.get(mark, ""))
        if table.per_problem:
            for index in indices:
                item = detail.get(index) or detail.get(str(index))
                cells.append(_number(item["score"]) if item else "")
                if table.attempts:
                    cells.append(int(item["attempts"]) if item else "")
                if table.times:
                    cells.append(format_time(int(item["time"]), start_time) if item else "")
        cells.append(_number(float(row.get("score", 0))))
        if not table.per_problem:
            if table.attempts:
                cells.append(sum(int(item["attempts"]) for item in detail.values()))
            if table.times:
                scored = int(row.get("submit_time", 0)) if row.get("score") else 0
                cells.append(format_time(scored, start_time))
        body.append(tuple(cells))
    return RankingTable(tuple(headers), tuple(kinds), tuple(body), marks, title)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _safe_csv(value: object) -> str:
    text = _text(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def write_markdown(table: RankingTable, destination: Path) -> Path:
    def cell(value: object) -> str:
        return _text(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    lines = [
        "| " + " | ".join(table.headers) + " |",
        "| " + " | ".join("---:" if kind != "text" else "---" for kind in table.kinds) + " |",
    ]
    lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in table.rows]
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def write_csv(table: RankingTable, destination: Path) -> Path:
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(table.headers)
        for row in table.rows:
            writer.writerow(
                [_safe_csv(v) if k == "text" else _text(v) for v, k in zip(row, table.kinds)]
            )
    return destination


_STYLE = (
    "<style>body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:1200px;"
    "padding:0 1rem;color:#202124}table{border-collapse:collapse;width:100%}"
    "th,td{padding:.4rem .6rem;border-bottom:1px solid #ddd;text-align:left}"
    "td.n,th.n{text-align:right}th{background:#f5f5f5}</style>"
)
_HTML_FILLS = {"cheater": "#f8d7da", "suspect": "#fff3cd", "manager": "#e9ecef"}


def write_html(table: RankingTable, destination: Path) -> Path:
    title = html.escape(table.title)
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        _STYLE,
        f"</head><body><h1>{title}</h1><p>本地提交推算 · 非官方排名</p><table><thead><tr>",
    ]
    parts += [
        f'<th class="{"n" if kind != "text" else ""}">{html.escape(header)}</th>'
        for header, kind in zip(table.headers, table.kinds)
    ]
    parts.append("</tr></thead><tbody>")
    for row, mark in zip(table.rows, table.marks):
        fill = _HTML_FILLS.get(mark)
        parts.append(f'<tr style="background:{fill}">' if fill else "<tr>")
        parts += [
            f'<td class="{"n" if kind != "text" else ""}">{html.escape(_text(value))}</td>'
            for value, kind in zip(row, table.kinds)
        ]
        parts.append("</tr>")
    parts.append("</tbody></table></body></html>\n")
    destination.write_text("\n".join(parts), encoding="utf-8")
    return destination


def write_table(table: RankingTable, format_name: str, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "xlsx":
        from ojaudit.plugins.exporters.xlsx import export_xlsx

        return export_xlsx(table, path)
    writers = {"md": write_markdown, "csv": write_csv, "html": write_html}
    if format_name not in writers:
        raise ValueError("仅支持 xlsx/md/csv/html")
    return writers[format_name](table, path)


def preview_rows(table: RankingTable, limit: int | None = None) -> Sequence[tuple[Any, ...]]:
    return table.rows if limit is None else table.rows[:limit]
