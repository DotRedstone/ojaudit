"""
Module: Detector / classifier
Description: 将 pair 相似度信号映射为可解释的复核等级。
Scope: Detector
Notes: 等级不代表事实认定；阈值可配置且输出稳定。
"""

from __future__ import annotations

from collections.abc import Iterable


def classify(findings: Iterable[dict], parameters: dict | None = None) -> list[dict]:
    options = parameters or {}
    high = float(options.get("high_threshold", 0.85))
    medium = float(options.get("medium_threshold", 0.65))
    if not 0 <= medium <= high <= 1:
        raise ValueError("分类阈值必须满足 0 <= medium <= high <= 1")
    output = []
    for finding in findings:
        similarity = round(float(finding.get("similarity", 0.0)), 4)
        if similarity >= high:
            level = "高"
            reason = f"相似度 {similarity:.1%}，达到高等级阈值 {high:.1%}"
        elif similarity >= medium:
            level = "中"
            reason = f"相似度 {similarity:.1%}，达到中等级阈值 {medium:.1%}"
        else:
            level = "低"
            reason = f"相似度 {similarity:.1%}，低于中等级阈值"
        output.append({**finding, "level": level, "classification_reason": reason})
    return sorted(
        output,
        key=lambda row: (
            row.get("problem", -1),
            row.get("language", ""),
            tuple(row.get("pair", ())),
            row["level"],
        ),
    )
