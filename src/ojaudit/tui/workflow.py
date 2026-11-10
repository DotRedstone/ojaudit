"""TUI 采集检测工作流与跨比赛待复核数据，保持核心业务接口复用。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ojaudit.cli import _analyze
from ojaudit.cli_operations import import_bundle
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
    """复用 CLI 同一检测配置与持久化路径。"""
    with Store(db_path) as store:
        return _analyze(store, contest.platform, contest.contest_id, 0.5)
