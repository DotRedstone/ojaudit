"""
Module: Detector / timeline
Description: 两名选手同题提交的通过先后、时间差、失败序列与方向有效性。
Scope: Detector
Notes:
- 只依据提交时间与结果，不推断现实中的代码传播关系。
- 提交时间为毫秒；输出的秒数保留一位小数。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ojaudit.core.schema import Submission, is_accepted


def error_type(verdict: str) -> str:
    checks = (
        (("编译", "Compile"), "编译错误"),
        (("超时", "Time", "TLE"), "超时"),
        (("内存", "Memory"), "内存超限"),
        (("答案", "Wrong", "WA"), "答案错误"),
        (("段错误", "Seg"), "段错误"),
        (("格式", "Presentation"), "格式错误"),
        (("输出",), "输出超限"),
    )
    for markers, label in checks:
        if any(marker in verdict for marker in markers):
            return label
    return verdict or "未知"


def analyze_timeline(left: Iterable[Submission], right: Iterable[Submission]) -> dict[str, Any]:
    a = sorted(left, key=lambda item: (item.submit_time, item.submission_id))
    b = sorted(right, key=lambda item: (item.submit_time, item.submission_id))
    first_delta = round(abs(a[0].submit_time - b[0].submit_time) / 1000, 1)
    ac_a = min((item.submit_time for item in a if is_accepted(item.verdict)), default=None)
    ac_b = min((item.submit_time for item in b if is_accepted(item.verdict)), default=None)
    who = (
        "A"
        if ac_a is not None and (ac_b is None or ac_a <= ac_b)
        else ("B" if ac_b is not None else None)
    )
    delta = round(abs(ac_a - ac_b) / 1000, 1) if ac_a is not None and ac_b is not None else None
    direction = (who == "A" and ac_a is not None and b[0].submit_time >= ac_a) or (
        who == "B" and ac_b is not None and a[0].submit_time >= ac_b
    )
    later = b if who == "A" else a
    later_ac = ac_b if who == "A" else ac_a
    failures = [
        error_type(item.verdict)
        for item in later
        if not is_accepted(item.verdict) and (later_ac is None or item.submit_time < later_ac)
    ]
    return {
        "who_first": who,
        "delta_seconds": delta,
        "first_submit_delta": first_delta,
        "later_failures_before_ac": len(failures),
        "direction_valid": bool(direction),
        "error_types": failures[:10],
    }
