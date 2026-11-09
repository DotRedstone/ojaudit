"""
Module: Detector / template
Description: 迁移旧检测器的高频 n-gram 与人群模板统计。
Scope: Detector
Notes: 模板统计按不同 UID 计数，不按提交次数计数。
"""

from __future__ import annotations

from collections import defaultdict

from ojaudit.plugins.detectors.similarity import ngrams


def build_usage(
    tokens_by_uid: dict[str, list[str]], size: int = 5
) -> dict[tuple[str, ...], set[str]]:
    usage: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for uid, tokens in sorted(tokens_by_uid.items()):
        for gram in ngrams(tokens, size):
            usage[gram].add(uid)
    return dict(usage)


def common_ratio(
    tokens: list[str],
    usage: dict[tuple[str, ...], set[str]],
    size: int = 5,
    rare_threshold: int = 3,
) -> float:
    grams = ngrams(tokens, size)
    if not grams:
        return 1.0
    common = sum(1 for gram in grams if len(usage.get(gram, set())) > rare_threshold)
    return round(common / len(grams), 4)


def crowd_count(normalized_code_by_uid: dict[str, str], uid: str) -> int:
    import hashlib
    import re

    target = re.sub(r"\s+", "", normalized_code_by_uid[uid])
    digest = hashlib.md5(target.encode()).hexdigest()
    return sum(
        hashlib.md5(re.sub(r"\s+", "", code).encode()).hexdigest() == digest
        for code in normalized_code_by_uid.values()
    )


def exclude_crowd_template(
    normalized_code_by_uid: dict[str, str], uid: str, threshold: int = 3
) -> bool:
    if threshold < 1:
        raise ValueError("人群模板阈值必须为正整数")
    return crowd_count(normalized_code_by_uid, uid) >= threshold
