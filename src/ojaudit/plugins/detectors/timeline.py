"""
Module: Detector / timeline
Description: 迁移旧检测器的 AC 顺序、失败序列与方向有效性分析。
Scope: Detector
Notes: 时间线只依据提交时间与 verdict，不推断现实中的代码传播关系。
"""

from __future__ import annotations

from collections.abc import Iterable

from ojaudit.core.schema import Submission
from ojaudit.plugins.detectors.nowcoder import _timeline


def analyze_timeline(left: Iterable[Submission], right: Iterable[Submission]) -> dict:
    """返回旧检测器兼容的时间线字段。"""
    return _timeline(list(left), list(right))
