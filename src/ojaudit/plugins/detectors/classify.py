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
    # 去空白后不完全相同时，高 L2 还必须伴随至少一个共享的稀有片段：
    # 简单题的常见写法彼此 L2 也很高，但所有片段都被许多人使用，不构成证据。
    if md5_equal or (l2 >= thresholds["solid_l2"] and rare_score > 0):
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


def could_flag(
    identical: bool,
    rare: dict[str, Any],
    timeline: dict[str, Any] | None,
    thresholds: dict[str, Any],
) -> bool:
    """不计算 L1/L2/L3 时，判断该对是否仍可能得到非「排除」的等级。

    返回 False 时 classify() 必然返回「排除」，可以跳过昂贵的逐字比对。
    """
    rare_score = rare.get("score", 0.0)
    timeline = timeline or {}
    if identical:
        return True
    if rare_score >= min(thresholds["mid_strong_rare"], thresholds["suspicious_rare"]):
        return True
    return (
        rare_score > 0
        and bool(timeline.get("direction_valid"))
        and timeline.get("delta_seconds") is not None
        and timeline["delta_seconds"] < thresholds["solid_delta_seconds"]
    )
