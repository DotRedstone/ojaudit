"""
Module: Detector / template
Description: 统计同题同语言中去空白后代码完全相同的人数，识别公共模板。
Scope: Detector
Notes: 按不同 UID 计数，不按提交次数计数。
"""

from __future__ import annotations

from collections import Counter

from ojaudit.plugins.detectors.similarity import space_digest


def crowd_counts(code_by_uid: dict[str, str]) -> dict[str, int]:
    """每人的代码与多少人（含自己）完全相同。"""
    digests = {uid: space_digest(code) for uid, code in code_by_uid.items()}
    counts = Counter(digests.values())
    return {uid: counts[digest] for uid, digest in digests.items()}
