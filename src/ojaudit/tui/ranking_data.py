"""
Module: TUI / ranking data
Description: 从本地提交推导预览榜单并复用核心排名策略和导出插件。
Scope: TUI
Notes:
- 当前 schema 不含官方榜单；推导结果显式标注非官方。
- 导出路径使用 XDG 数据目录并限制路径段，不访问网络。
"""

from __future__ import annotations

import re
from pathlib import Path

from ojaudit.core.config import data_dir
from ojaudit.core.people import HiddenPerson
from ojaudit.core.ranking import FinalRanking, RankingOptions, build_final_ranking
from ojaudit.plugins.exporters.csv import export_csv
from ojaudit.plugins.exporters.html import export_html
from ojaudit.plugins.exporters.markdown import export_markdown
from ojaudit.tui.review_data import ReviewData


def derived_rows(data: ReviewData) -> list[dict]:
    people = data.people()
    entries = data.submissions()
    best: dict[tuple[str, int], tuple[float, int]] = {}
    for item in entries:
        key = (str(item["uid"]), int(item["problem_index"]))
        score = float(item["score"])
        time = int(item["submit_time"])
        old = best.get(key)
        if old is None or score > old[0] or (score == old[0] and time < old[1]):
            best[key] = (score, time)
    rows = []
    for person in people:
        uid = str(person["uid"])
        records = [record for (person_uid, _), record in best.items() if person_uid == uid]
        score = sum(record[0] for record in records)
        last_time = max((record[1] for record in records), default=0)
        rows.append(
            {
                "platform": data.contest.platform,
                "uid": uid,
                "name": person["name"],
                "score": score,
                "submit_time": last_time,
            }
        )
    rows.sort(key=lambda row: (-row["score"], row["submit_time"], row["uid"]))
    return [{**row, "rank": i} for i, row in enumerate(rows, 1)]


def final_ranking(data: ReviewData, policy: RankingOptions) -> FinalRanking:
    people = data.people()
    marks = {str(person["uid"]): str(person["mark"]) for person in people if person["mark"]}
    hidden = [
        HiddenPerson(data.contest.platform, str(person["uid"]), str(person["name"]))
        for person in people
        if person["hidden"]
    ]
    return build_final_ranking(derived_rows(data), marks, hidden, policy)


def pending_warnings(data: ReviewData) -> tuple[str, ...]:
    messages = []
    pending = [
        item for item in data.findings() if not item["is_stale"] and item["status"] == "待复核"
    ]
    if pending:
        messages.append(f"仍有 {len(pending)} 条线索待复核")
    unmarked = [person for person in data.people() if not person["hidden"] and not person["mark"]]
    if unmarked:
        messages.append(f"仍有 {len(unmarked)} 名选手未人工标记")
    return tuple(messages)


def _safe_part(part: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", part):
        raise ValueError("导出路径的平台与比赛 ID 仅允许字母、数字、下划线和连字符")
    return part


def export_ranking(
    data: ReviewData, policy: RankingOptions, format_name: str, base_dir: str | Path | None = None
) -> Path:
    exporters = {"md": export_markdown, "csv": export_csv, "html": export_html}
    if format_name not in exporters:
        raise ValueError("仅支持 md/csv/html")
    rows = final_ranking(data, policy).rows
    target = (
        (Path(base_dir) if base_dir is not None else data_dir() / "exports")
        / _safe_part(data.contest.platform)
        / _safe_part(data.contest.contest_id)
    )
    destination = target / f"ranking.{format_name}"
    # 原有导出器面向证据列。此处保留核心排序结果并映射至现有列，避免修改插件。
    adapted = [
        {
            "uid": row["uid"],
            "problem": f"排名 {row['rank']}",
            "language": "",
            "pair": "",
            "similarity": row.get("score", ""),
            "level": row.get("person_mark", "正常"),
            "reason": f"推导榜单（非官方）· {row.get('name', '')}",
            "scores": row.get("score", ""),
            "mark": row.get("person_mark", "正常"),
        }
        for row in rows
    ]
    return exporters[format_name](adapted, destination)
