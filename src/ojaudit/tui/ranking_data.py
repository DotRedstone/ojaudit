"""
Module: TUI / ranking data
Description: 把 TUI 的只读比赛数据交给 core.ranking 推导、排名与导出，并汇总待处理提醒。
Scope: TUI
Notes: 推导规则只在 core.ranking 中实现，CLI 与 TUI 结果一致。
"""

from __future__ import annotations

from pathlib import Path

from ojaudit.core.people import HiddenPerson
from ojaudit.core.ranking import (
    FinalRanking,
    RankingOptions,
    build_final_ranking,
    default_export_path,
    derive_rows,
)
from ojaudit.core.ranking import export_ranking as export_rows
from ojaudit.tui.review_data import ReviewData


def derived_rows(data: ReviewData) -> list[dict]:
    return derive_rows(
        data.contest.platform,
        ((str(p["uid"]), str(p["name"])) for p in data.people()),
        (
            (
                str(s["uid"]),
                int(s["problem_index"]),
                float(s["score"]),
                int(s["submit_time"]),
                str(s["phase"]),
            )
            for s in data.submissions()
        ),
    )


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


def export_ranking(
    data: ReviewData, policy: RankingOptions, format_name: str, base_dir: str | Path | None = None
) -> Path:
    destination = default_export_path(
        data.contest.platform,
        data.contest.contest_id,
        format_name,
        Path(base_dir) if base_dir is not None else None,
    )
    return export_rows(final_ranking(data, policy), format_name, destination)
