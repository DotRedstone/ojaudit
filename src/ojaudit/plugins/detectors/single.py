"""
Module: Detector / single
Description: 提取单份提交的代码规模与注释比例信号。
Scope: Detector
Notes: 单人信号仅供审查参考，不得单独作为违规结论。
"""

from __future__ import annotations

from collections.abc import Iterable

from ojaudit.core.schema import Submission


def code_metrics(code: str) -> dict[str, int | float]:
    lines = (code or "").splitlines()
    loc = comments = blanks = 0
    in_block = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blanks += 1
        elif in_block:
            comments += 1
            if "*/" in stripped:
                in_block = False
        elif stripped.startswith("/*"):
            comments += 1
            if "*/" not in stripped:
                in_block = True
        elif stripped.startswith(("//", "#")):
            comments += 1
        else:
            loc += 1
    ratio = comments / len(lines) if lines else 0.0
    return {"loc": loc, "comments": comments, "blanks": blanks, "comment_ratio": round(ratio, 4)}


def analyze_single(submissions: Iterable[Submission] | object) -> list[dict]:
    items = getattr(submissions, "submissions", submissions)
    rows = []
    for item in items:
        if not item.code:
            continue
        metrics = code_metrics(item.code)
        rows.append(
            {
                "uid": item.uid,
                "problem": item.problem_index,
                "submission_id": item.submission_id,
                "language": item.language,
                "metrics": metrics,
                "reason": f"代码 {metrics['loc']} 行，注释占比 {metrics['comment_ratio']:.1%}",
            }
        )
    return sorted(rows, key=lambda row: (row["uid"], row["problem"], row["submission_id"]))
