"""
Module: Detector / similarity
Description: 迁移旧检测器的三口径相似度与稀有 n-gram 计算。
Scope: Detector
Notes: 浮点分数固定为四位小数。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ojaudit.plugins.detectors.nowcoder import _ngrams, _ratio, normalize_tokens


def compute_scores(code_a: str, code_b: str, language: str) -> dict[str, Any]:
    import hashlib
    import re

    tokens_a = normalize_tokens(code_a, language)
    tokens_b = normalize_tokens(code_b, language)
    left = re.sub(r"\s+", "", code_a)
    right = re.sub(r"\s+", "", code_b)
    return {
        "L1": round(_ratio(code_a, code_b), 4),
        "L2": round(_ratio(left, right), 4),
        "L3": round(_ratio(tokens_a, tokens_b), 4),
        "md5_ws_equal": hashlib.md5(left.encode()).hexdigest()
        == hashlib.md5(right.encode()).hexdigest(),
    }


def ngrams(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    if size < 1:
        raise ValueError("n-gram 窗口必须为正整数")
    return _ngrams(tokens, size)


def build_rare_sets(
    tokens_by_uid: dict[str, list[str]], size: int = 5, rare_threshold: int = 3
) -> dict[str, set[tuple[str, ...]]]:
    if rare_threshold < 1:
        raise ValueError("稀有阈值必须为正整数")
    usage: dict[tuple[str, ...], set[str]] = {}
    for uid, tokens in sorted(tokens_by_uid.items()):
        for gram in ngrams(tokens, size):
            usage.setdefault(gram, set()).add(uid)
    return {
        uid: {gram for gram in ngrams(tokens, size) if len(usage[gram]) <= rare_threshold}
        for uid, tokens in sorted(tokens_by_uid.items())
    }


def rare_between(
    left: Iterable[tuple[str, ...]], right: Iterable[tuple[str, ...]]
) -> dict[str, Any]:
    a, b = set(left), set(right)
    shared = a & b
    score = len(shared) / min(len(a), len(b)) if a and b else 0.0
    return {
        "shared": len(shared),
        "score": round(score, 4),
        "samples": [" ".join(gram) for gram in sorted(shared)[:8]],
    }
