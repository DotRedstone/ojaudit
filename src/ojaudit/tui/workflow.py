"""
Module: TUI / workflow
Description: 后台采集、入库与分析的同步步骤，以及跨比赛待复核条目。
Scope: TUI
Notes: 在后台线程中运行；每步独立打开 Store，不跨线程共享连接。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ojaudit.core.analysis import run_analysis
from ojaudit.core.ingest import import_bundle
from ojaudit.core.schema import Contest
from ojaudit.core.store import Store
from ojaudit.tui.data import LocalContests
from ojaudit.tui.review_data import ReviewData


@dataclass(frozen=True)
class PendingEntry:
    contest: Contest
    kind: str
    finding: dict[str, Any] | None = None
    uid: str = ""


def pending_entries(local: LocalContests) -> list[PendingEntry]:
    """只列当前分析轮次仍待复核的线索和存疑人员。"""
    result: list[PendingEntry] = []
    for entry in local.list_contests(show_all=True):
        contest = entry.contest
        data = ReviewData(local, contest)
        for finding in data.findings():
            if not finding["is_stale"] and finding["status"] == "待复核":
                result.append(PendingEntry(contest, "finding", finding))
        for person in data.people():
            if not person["hidden"] and person["mark"] == "suspect":
                result.append(PendingEntry(contest, "person", uid=person["uid"]))
    return result


def persist_bundle(db_path: str | Path, bundle: Any) -> Contest:
    """后台线程独立打开 SQLite，避免跨线程共享连接。"""
    with Store(db_path) as store:
        import_bundle(store, bundle)
    return bundle.contest


def analyze_local(db_path: str | Path, contest: Contest) -> str:
    """与 CLI 共用 core.analysis 的配置与持久化。"""
    with Store(db_path) as store:
        return run_analysis(store, contest.platform, contest.contest_id, created_from="tui").run_id
