"""
Module: TUI / contest list overview
Description: 汇总本地比赛日期、采集/分析状态、线索优先级与复核进度。
Scope: TUI
Notes: 只读本机 SQLite；不将推导榜单误写成官方排名。
"""

from __future__ import annotations

from datetime import UTC, datetime

from ojaudit.core.schema import Contest
from ojaudit.tui.data import LocalContests
from ojaudit.tui.review_data import ReviewData


def _date(timestamp: int | None) -> str:
    if timestamp is None:
        return "日期未知"
    try:
        seconds = timestamp / 1000 if timestamp > 10**11 else timestamp
        return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d")
    except (OverflowError, ValueError, TypeError, OSError):
        return "日期未知"


def contest_list_description(local: LocalContests, contest: Contest) -> str:
    stats = local.stats(contest)
    review = ReviewData(local, contest)
    state = "已分析" if review.latest_run() else ("已采集" if stats.submissions else "未采集")
    current = [row for row in review.findings() if not row["is_stale"]]
    counts = {
        name: sum(str(row["verdict_level"]).lower() == name for row in current)
        for name in ("high", "medium", "low")
    }
    checked = sum(row["status"] != "待复核" for row in current)
    date = _date(contest.start_time or contest.end_time)
    return (
        f"{date} · 提交 {stats.submissions} · {state} "
        f"· H/M/L {counts['high']}/{counts['medium']}/{counts['low']} "
        f"· 复核 {checked}/{len(current)}"
    )
