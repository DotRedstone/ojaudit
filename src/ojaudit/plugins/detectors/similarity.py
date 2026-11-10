"""
Module: Detector / similarity
Description: 三口径相似度（原文、去空白、词法归一）与稀有 n-gram 共享度。
Scope: Detector
Notes: 浮点分数固定为四位小数，保证结果可逐字节复现。
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ojaudit.plugins.detectors.tokens import ngrams, normalize_tokens, ratio

_SPACE = re.compile(r"\s+")


def strip_space(code: str) -> str:
    return _SPACE.sub("", code or "")


def space_digest(code: str) -> str:
    """去空白后的代码摘要，用于判定完全相同与统计同码人数。"""
    return hashlib.md5(strip_space(code).encode()).hexdigest()


def compute_scores(
    code_a: str,
    code_b: str,
    language: str,
    tokens_a: list[str] | None = None,
    tokens_b: list[str] | None = None,
) -> dict[str, Any]:
    tokens_a = tokens_a if tokens_a is not None else normalize_tokens(code_a, language)
    tokens_b = tokens_b if tokens_b is not None else normalize_tokens(code_b, language)
    left, right = strip_space(code_a), strip_space(code_b)
    return {
        "L1": round(ratio(code_a, code_b), 4),
        "L2": round(ratio(left, right), 4),
        "L3": round(ratio(tokens_a, tokens_b), 4),
        "md5_ws_equal": space_digest(code_a) == space_digest(code_b),
    }


def build_rare_sets(
    tokens_by_uid: dict[str, list[str]], size: int = 5, rare_threshold: int = 3
) -> dict[str, set[tuple[str, ...]]]:
    """每人代码中「最多被 rare_threshold 人使用」的 n-gram 集合。"""
    if rare_threshold < 1:
        raise ValueError("稀有阈值必须为正整数")
    grams = {uid: ngrams(tokens, size) for uid, tokens in tokens_by_uid.items()}
    usage: dict[tuple[str, ...], int] = defaultdict(int)
    for items in grams.values():
        for gram in items:
            usage[gram] += 1
    return {
        uid: {gram for gram in items if usage[gram] <= rare_threshold}
        for uid, items in sorted(grams.items())
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
