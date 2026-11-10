"""
Module: Detector / fingerprint
Description: Winnowing 指纹与 Jaccard 相似度，用作候选对的廉价初筛。
Scope: Detector
Notes: 只在同题同语言内比较；结果仅决定是否进入精细比对，不单独构成结论。
"""

from __future__ import annotations

import re

_STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
_COMMENT = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/|^[ \t]*#[^\n]*", re.MULTILINE)
_SPACE = re.compile(r"\s+")


def _normalized(code: str) -> str:
    value = _STRING.sub(" STR ", code or "")
    value = _COMMENT.sub(" ", value)
    return _SPACE.sub("", value)


def _hash(text: str) -> int:
    value = 5381
    for char in text:
        value = ((value << 5) + value + ord(char)) & 0xFFFFFFFF
    return value


def winnow(code: str, k: int = 5, window: int = 4) -> frozenset[int]:
    """返回代码的 Winnowing 指纹集合；过短的代码返回空集合。"""
    if k < 1 or window < 1:
        raise ValueError("k 和 window 必须为正整数")
    text = _normalized(code)
    if len(text) < k + window - 1:
        return frozenset()
    hashes = [_hash(text[index : index + k]) for index in range(len(text) - k + 1)]
    return frozenset(
        min(hashes[index : index + window]) for index in range(len(hashes) - window + 1)
    )


def jaccard(left: frozenset[int], right: frozenset[int]) -> float:
    if not left or not right:
        return 0.0
    shared = len(left & right)
    return shared / (len(left) + len(right) - shared)
