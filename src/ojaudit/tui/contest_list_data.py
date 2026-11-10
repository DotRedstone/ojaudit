"""
Module: TUI / contest list overview
Description: 汇总本地比赛日期、采集/分析状态、线索分级与复核进度。
Scope: TUI
Notes: 只读本机 SQLite；不将推导榜单误写成官方排名。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ojaudit.core.schema import Contest
from ojaudit.tui.data import ContestStats, LocalContests
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.ui import level_rank


@dataclass(frozen=True, slots=True)
class ContestSummary:
    stats: ContestStats
    date: str
    state: str
    levels: tuple[int, int, int]  # 实锤 / 中偏强 / 存疑（含 high/medium/low）
    findings: int
    reviewed: int
    marked: int

    @property
    def submissions(self) -> int:
        return self.stats.submissions


def _date(timestamp: int | None) -> str:
    if timestamp is None:
        return "日期未知"
    try:
        seconds = timestamp / 1000 if timestamp > 10**11 else timestamp
        return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d")
    except (OverflowError, ValueError, TypeError, OSError):
        return "日期未知"


def contest_summary(local: LocalContests, contest: Contest) -> ContestSummary:
    stats = local.stats(contest)
    review = ReviewData(local, contest)
    state = "已分析" if review.latest_run() else ("已采集" if stats.submissions else "未采集")
    current = [row for row in review.findings() if not row["is_stale"]]
    levels = tuple(
        sum(level_rank(row["verdict_level"]) == rank for row in current) for rank in (0, 1, 2)
    )
    marked = sum(1 for person in review.people() if person["mark"])
    return ContestSummary(
        stats=stats,
        date=_date(contest.start_time or contest.end_time),
        state=state,
        levels=levels,  # type: ignore[arg-type]
        findings=len(current),
        reviewed=sum(row["status"] != "待复核" for row in current),
        marked=marked,
    )


def contest_list_description(local: LocalContests, contest: Contest) -> str:
    """纯文本摘要，供 CLI/测试使用；等级计数按 实锤/中偏强/存疑 归并。"""
    summary = contest_summary(local, contest)
    high, medium, low = summary.levels
    return (
        f"{summary.date} · 提交 {summary.submissions} · {summary.state} "
        f"· 线索 {high}/{medium}/{low} · 复核 {summary.reviewed}/{summary.findings}"
    )
