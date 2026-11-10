"""
Module: Detector / engine
Description: 内置检测流水线：同题同语言分组 → 指纹初筛候选对 → 三口径相似度、稀有片段、
    模板人数与时间线 → 分级。
Scope: Detector
Notes:
- 指纹 Jaccard 低于阈值的选手对不会成为线索，因此先用指纹筛出候选；
  候选中按稀有片段与时间线已能确定为「排除」的，也跳过昂贵的逐字比对。
  两步都只省计算，结果与全部比对完全相同（exhaustive=True 可关闭以便测试）。
- 只返回分级不是「排除」的选手对。
- 只比较不同 UID 的代表提交（最高分 → 最长代码 → 最早提交）；输出排序稳定。
- 不访问网络或数据库，结论只作为人工复核线索。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ojaudit.core.schema import Submission
from ojaudit.plugins.detectors.classify import DEFAULT_THRESHOLDS, classify, could_flag
from ojaudit.plugins.detectors.fingerprint import jaccard, winnow
from ojaudit.plugins.detectors.similarity import (
    build_rare_sets,
    compute_scores,
    rare_between,
    space_digest,
)
from ojaudit.plugins.detectors.template import crowd_counts
from ojaudit.plugins.detectors.timeline import analyze_timeline
from ojaudit.plugins.detectors.tokens import normalize_tokens


@dataclass(frozen=True, slots=True)
class EngineConfig:
    threshold: float = 0.5  # 指纹 Jaccard 初筛阈值
    k: int = 5
    window: int = 4
    ngram_size: int = 5
    rare_threshold: int = 3
    thresholds: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    enable_template: bool = True
    enable_timeline: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.threshold <= 1:
            raise ValueError("threshold 必须在 0 到 1 之间")
        missing = set(DEFAULT_THRESHOLDS) - set(self.thresholds)
        if missing:
            raise ValueError(f"缺少分级阈值：{', '.join(sorted(missing))}")


def _representative(items: list[Submission]) -> Submission:
    return max(items, key=lambda item: (item.score, len(item.code), -item.submit_time))


def _reasons(similarity: float, crowd: int, rare: dict[str, Any], verdict: str) -> list[str]:
    return [
        f"Winnowing/Jaccard 相似度 {similarity:.1%}",
        f"模板相同人数：{crowd}",
        f"稀有片段共享：{rare['shared']}",
        f"检测分级：{verdict}（仅供人工复核）",
    ]


def analyze(
    submissions: Iterable[Submission],
    config: EngineConfig | None = None,
    *,
    exhaustive: bool = False,
) -> list[dict[str, Any]]:
    """返回需要人工复核的选手对（分级不是「排除」），按题目、语言、选手排序。"""
    config = config or EngineConfig()
    groups: dict[tuple[int, str], dict[str, list[Submission]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in submissions:
        if item.code.strip():
            groups[(item.problem_index, item.language)][item.uid].append(item)

    results = []
    for (problem, language), people in sorted(groups.items()):
        reps = {uid: _representative(items) for uid, items in sorted(people.items())}
        prints = {uid: winnow(rep.code, config.k, config.window) for uid, rep in reps.items()}
        uids = sorted(reps)
        candidates = []
        for index, uid_a in enumerate(uids):
            for uid_b in uids[index + 1 :]:
                similarity = jaccard(prints[uid_a], prints[uid_b])
                if similarity >= config.threshold:
                    candidates.append((uid_a, uid_b, similarity))
        if not candidates:
            continue

        tokens = {uid: normalize_tokens(rep.code, language) for uid, rep in reps.items()}
        rare = build_rare_sets(tokens, config.ngram_size, config.rare_threshold)
        crowds = crowd_counts({uid: rep.code for uid, rep in reps.items()})
        digests = {uid: space_digest(rep.code) for uid, rep in reps.items()}
        for uid_a, uid_b, similarity in candidates:
            a, b = reps[uid_a], reps[uid_b]
            rare_info = rare_between(rare[uid_a], rare[uid_b])
            timeline = (
                analyze_timeline(people[uid_a], people[uid_b]) if config.enable_timeline else {}
            )
            identical = digests[uid_a] == digests[uid_b]
            if not exhaustive and not could_flag(identical, rare_info, timeline, config.thresholds):
                continue
            scores = compute_scores(a.code, b.code, language, tokens[uid_a], tokens[uid_b])
            crowd = crowds[uid_a] if identical and config.enable_template else 1
            verdict = classify(scores, rare_info, timeline, config.thresholds, crowd)
            if verdict == "排除":
                continue
            results.append(
                {
                    "pair": [uid_a, uid_b],
                    "problem": problem,
                    "language": language,
                    "verdict": verdict,
                    "similarity": round(similarity, 4),
                    "scores": scores,
                    "rare": rare_info,
                    "timeline": timeline,
                    "crowd_count": crowd,
                    "reasons": _reasons(similarity, crowd, rare_info, verdict),
                }
            )
    return sorted(
        results,
        key=lambda row: (row["problem"], row["language"], row["pair"], row["verdict"]),
    )
