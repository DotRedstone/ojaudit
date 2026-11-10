"""
Module: Detector / classify
Description: 分级规则的唯一实现：把相似度、稀有片段、时间线与同码人数映射为 实锤/中偏强/存疑/排除。
Scope: Detector
Notes: 结果是人工复核线索，不构成自动违规认定；规则与旧 nowcoder-collect 一致。
"""

from __future__ import annotations

from typing import Any

VERDICT_ORDER = {"实锤": 0, "中偏强": 1, "存疑": 2, "排除": 3}
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "solid_l2": 0.98,
    "solid_delta_seconds": 1800,
    "mid_strong_rare": 0.5,
    "mid_strong_l3": 0.85,
    "suspicious_l3": 0.8,
    "suspicious_rare": 0.3,
    "crowd_threshold": 3,
}


def classify(
    scores: dict[str, Any],
    rare: dict[str, Any],
    timeline: dict[str, Any] | None,
    thresholds: dict[str, Any],
    crowd_count: int = 0,
) -> str:
    l2 = scores.get("L2", 0.0)
    l3 = scores.get("L3", 0.0)
    md5_equal = scores.get("md5_ws_equal", False)
    rare_score = rare.get("score", 0.0)
    timeline = timeline or {}
    if md5_equal and crowd_count >= thresholds.get("crowd_threshold", 3):
        return "排除"
    if md5_equal or l2 >= thresholds["solid_l2"]:
        if (
            timeline.get("direction_valid")
            and timeline.get("delta_seconds") is not None
            and timeline["delta_seconds"] < thresholds["solid_delta_seconds"]
        ):
            return "实锤"
        if md5_equal:
            return "中偏强"
    if rare_score >= thresholds["mid_strong_rare"] and l3 >= thresholds["mid_strong_l3"]:
        return "中偏强"
    if l3 >= thresholds["suspicious_l3"] and rare_score >= thresholds["suspicious_rare"]:
        return "存疑"
    return "排除"
