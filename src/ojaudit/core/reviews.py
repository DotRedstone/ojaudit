"""
Module: Core / reviews
Description: 线索级人工复核状态与新分析结果失效提示。
Scope: Core
Notes: 复核记录以 run_id 保存；新分析不会覆盖旧 run 的人工状态。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

REVIEW_STATUSES = ("已核查", "无需跟进", "需进一步核实")
DEFAULT_REVIEW_STATUS = "待复核"


def finding_key(row: dict[str, Any]) -> tuple[str, str, int, str]:
    left, right = sorted((str(row["uid_a"]), str(row["uid_b"])))
    return left, right, int(row["problem_index"]), str(row["language"])


def review_status(review: dict[str, Any] | None) -> str:
    return DEFAULT_REVIEW_STATUS if review is None else str(review["status"])


def stale_review_keys(
    reviews: Iterable[dict[str, Any]], current_findings: Iterable[dict[str, Any]]
) -> frozenset[tuple[str, str, int, str]]:
    active = {finding_key(item) for item in current_findings}
    return frozenset(finding_key(item) for item in reviews if finding_key(item) not in active)


def annotate_review_staleness(
    reviews: Iterable[dict[str, Any]], current_findings: Iterable[dict[str, Any]]
) -> tuple[dict[str, Any], ...]:
    current = {finding_key(item) for item in current_findings}
    return tuple({**item, "is_stale": finding_key(item) not in current} for item in reviews)
