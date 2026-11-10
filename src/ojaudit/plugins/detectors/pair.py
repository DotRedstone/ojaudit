"""
Module: Detector / pair
Description: 使用 Winnowing 指纹与 Jaccard 相似度生成跨用户同题线索。
Scope: Detector
Notes: 结果仅作人工复核线索；不访问网络，不作自动违规判定。
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from ojaudit.core.schema import Submission


def _normalized(code: str) -> str:
    value = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', " STR ", code or "")
    value = re.sub(r"//[^\n]*|/\*[\s\S]*?\*/|^[ \t]*#[^\n]*", " ", value, flags=re.MULTILINE)
    return re.sub(r"\s+", "", value)


def _hash(text: str) -> int:
    value = 5381
    for char in text:
        value = ((value << 5) + value + ord(char)) & 0xFFFFFFFF
    return value


def winnow(code: str, k: int = 5, window: int = 4) -> tuple[int, ...]:
    if k < 1 or window < 1:
        raise ValueError("k 和 window 必须为正整数")
    text = _normalized(code)
    if len(text) < k + window - 1:
        return ()
    hashes = [_hash(text[index : index + k]) for index in range(len(text) - k + 1)]
    selected = set()
    for index in range(len(hashes) - window + 1):
        selected.add(min(hashes[index : index + window]))
    return tuple(sorted(selected))


def _jaccard(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def analyze_pair(
    submissions: Iterable[Submission] | object, parameters: dict | None = None
) -> list[dict]:
    items = getattr(submissions, "submissions", submissions)
    options = parameters or {}
    threshold = float(options.get("threshold", 0.5))
    k = int(options.get("k", 5))
    window = int(options.get("window", 4))
    if not 0 <= threshold <= 1:
        raise ValueError("threshold 必须在 0 到 1 之间")
    grouped: dict[tuple[int, str], dict[str, list[Submission]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in items:
        if item.code.strip():
            grouped[(item.problem_index, item.language)][item.uid].append(item)
    output = []
    for (problem, language), users in sorted(grouped.items()):
        reps = {
            uid: max(
                rows,
                key=lambda row: (row.score, len(row.code), -row.submit_time, row.submission_id),
            )
            for uid, rows in sorted(users.items())
        }
        fingerprints = {uid: winnow(row.code, k, window) for uid, row in reps.items()}
        uids = sorted(reps)
        for index, uid_a in enumerate(uids):
            for uid_b in uids[index + 1 :]:
                similarity = _jaccard(fingerprints[uid_a], fingerprints[uid_b])
                if similarity < threshold:
                    continue
                output.append(
                    {
                        "pair": [uid_a, uid_b],
                        "problem": problem,
                        "language": language,
                        "similarity": round(similarity, 4),
                        "reason": f"Winnowing/Jaccard 相似度 {similarity:.1%}",
                    }
                )
    return sorted(output, key=lambda row: (row["problem"], row["language"], row["pair"]))
