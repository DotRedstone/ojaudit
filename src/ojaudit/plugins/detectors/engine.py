"""
Module: Detector / engine
Description: 内置检测流水线：同题同语言分组 → 稀有片段倒排索引找候选对 → 三口径相似度、
    稀有片段、模板人数与时间线 → 分级。
Scope: Detector
Notes:
- 候选对 = 共享至少一个稀有片段的选手对 ∪ 去空白后完全相同的选手对。分级规则要求不完全
  相同的线索必须共享稀有片段，所以其余选手对必然是「排除」，不比较也不会漏；而稀有片段
  按定义最多被少数人使用，倒排索引的规模很小，不必两两比较。
  稀有片段阈值被设为 0 时规则不再要求共享片段，退回全部两两比对。
- 以前用原文 Winnowing 指纹做初筛：变量改名会大幅拉低指纹相似度，改名抄袭在初筛就被放过
  （一场 43 人的真实比赛漏掉 18 条中的 10 条）。指纹阈值现在默认 0（不额外限制），
  设为正数时作为额外条件。
- 候选中按稀有片段与时间线已能确定为「排除」的，或相似度的快速上界（difflib quick_ratio，
  必然不低于真实值）都达不到任何一条规则门槛的，跳过昂贵的逐字比对；结果与全部比对完全
  相同（exhaustive=True 可关闭这些加速以便测试）。
- 只返回分级不是「排除」的选手对。
- 只比较不同 UID 的代表提交（最高分 → 最长代码 → 最早提交）；输出排序稳定。
- 不访问网络或数据库，结论只作为人工复核线索。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any

from ojaudit.core.schema import Submission
from ojaudit.plugins.detectors.classify import DEFAULT_THRESHOLDS, classify, could_flag
from ojaudit.plugins.detectors.fingerprint import jaccard, winnow
from ojaudit.plugins.detectors.similarity import (
    build_rare_sets,
    compute_scores,
    rare_between,
    space_digest,
    strip_space,
)
from ojaudit.plugins.detectors.template import crowd_counts
from ojaudit.plugins.detectors.timeline import analyze_timeline
from ojaudit.plugins.detectors.tokens import normalize_tokens


@dataclass(frozen=True, slots=True)
class EngineConfig:
    threshold: float = 0.0  # 额外要求的指纹 Jaccard 下限；0 表示不限制
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


def _candidates(
    uids: list[str],
    rare: dict[str, set[tuple[str, ...]]],
    digests: dict[str, str],
    config: EngineConfig,
) -> list[tuple[str, str]]:
    """可能得到非「排除」等级的选手对：共享稀有片段，或去空白后完全相同。"""
    t = config.thresholds
    if min(t["mid_strong_rare"], t["suspicious_rare"]) <= 0:
        return list(combinations(uids, 2))  # 规则不再要求共享片段
    pairs: set[tuple[str, str]] = set()
    owners: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for uid in uids:
        for gram in rare[uid]:
            owners[gram].append(uid)
    for people in owners.values():
        pairs.update(combinations(sorted(people), 2))
    same: dict[str, list[str]] = defaultdict(list)
    for uid in uids:
        same[digests[uid]].append(uid)
    for people in same.values():
        # 同码人数达到模板阈值的会被判为公共模板而排除，不必展开。
        if config.enable_template and len(people) >= t.get("crowd_threshold", 3):
            continue
        pairs.update(combinations(sorted(people), 2))
    return sorted(pairs)


def _upper(left: Any, right: Any) -> float:
    """相似度的上界：先按长度、再按多重集重合，必然不低于 SequenceMatcher.ratio()。"""
    if not left and not right:
        return 1.0
    matcher = SequenceMatcher(None, left, right)
    bound = matcher.real_quick_ratio()
    return bound if bound == 0 else min(bound, matcher.quick_ratio())


def _could_reach(
    tokens: tuple[list[str], list[str]],
    codes: tuple[str, str],
    rare_score: float,
    thresholds: dict[str, Any],
) -> bool:
    """不完全相同的选手对，相似度上界能否达到某条规则的门槛；False 时必然「排除」。"""
    l3 = None
    for rare_needed, l3_needed in (
        (thresholds["mid_strong_rare"], thresholds["mid_strong_l3"]),
        (thresholds["suspicious_rare"], thresholds["suspicious_l3"]),
    ):
        if rare_score >= rare_needed:
            l3 = _upper(*tokens) if l3 is None else l3
            if l3 >= l3_needed:
                return True
    return rare_score > 0 and _upper(*codes) >= thresholds["solid_l2"]


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
        uids = sorted(reps)
        if len(uids) < 2:
            continue
        tokens = {uid: normalize_tokens(rep.code, language) for uid, rep in reps.items()}
        rare = build_rare_sets(tokens, config.ngram_size, config.rare_threshold)
        crowds = crowd_counts({uid: rep.code for uid, rep in reps.items()})
        digests = {uid: space_digest(rep.code) for uid, rep in reps.items()}
        pairs = (
            list(combinations(uids, 2)) if exhaustive else _candidates(uids, rare, digests, config)
        )
        prints: dict[str, frozenset[int]] = {}
        for uid_a, uid_b in pairs:
            for uid in (uid_a, uid_b):
                if uid not in prints:
                    prints[uid] = winnow(reps[uid].code, config.k, config.window)
            similarity = jaccard(prints[uid_a], prints[uid_b])
            if similarity < config.threshold:
                continue
            a, b = reps[uid_a], reps[uid_b]
            rare_info = rare_between(rare[uid_a], rare[uid_b])
            timeline = (
                analyze_timeline(people[uid_a], people[uid_b]) if config.enable_timeline else {}
            )
            identical = digests[uid_a] == digests[uid_b]
            if not exhaustive and not could_flag(identical, rare_info, timeline, config.thresholds):
                continue
            if (
                not exhaustive
                and not identical
                and not _could_reach(
                    (tokens[uid_a], tokens[uid_b]),
                    (strip_space(a.code), strip_space(b.code)),
                    rare_info["score"],
                    config.thresholds,
                )
            ):
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
