"""
Module: Test / detectors
Description: 用合成向量核对各检测阶段与旧 nowcoder-collect 规则一致，并验证流水线的确定性、
    初筛等价性与规模。
Scope: Test
Notes: 只使用合成代码与标识。
"""

import random
import time

import pytest

from ojaudit.core.schema import Submission
from ojaudit.plugins.detectors.classify import DEFAULT_THRESHOLDS, classify
from ojaudit.plugins.detectors.engine import EngineConfig, analyze
from ojaudit.plugins.detectors.fingerprint import jaccard, winnow
from ojaudit.plugins.detectors.similarity import build_rare_sets, compute_scores, rare_between
from ojaudit.plugins.detectors.template import crowd_counts
from ojaudit.plugins.detectors.timeline import analyze_timeline
from ojaudit.plugins.detectors.tokens import normalize_tokens

SAME = "int main(){int value=1;return value+1;}"


def sub(uid, code=SAME, when=1000, sid=None, verdict="Accepted", problem=0, language="cpp"):
    return Submission(
        "synthetic",
        "demo",
        sid or f"{uid}-{when}",
        uid,
        problem,
        language,
        verdict,
        100,
        when,
        "contest",
        code,
    )


def test_tokens_rename_identifiers_and_literals():
    assert normalize_tokens("int add(int x) { return x + 1; }", "cpp") == [
        "int",
        "v0",
        "(",
        "int",
        "v1",
        ")",
        "{",
        "return",
        "v1",
        "+",
        "NUM",
        ";",
        "}",
    ]
    assert normalize_tokens("int sum(int a){return a+1;}", "cpp") == normalize_tokens(
        "int calc(int value){return value+9;}", "cpp"
    )


def test_fingerprint_is_stable_and_validated():
    assert winnow(SAME) == winnow(SAME)
    assert jaccard(winnow(SAME), winnow(SAME)) == 1.0
    assert jaccard(winnow("x"), winnow(SAME)) == 0.0
    with pytest.raises(ValueError):
        winnow("abc", k=0)


def test_similarity_and_rare_vectors():
    scores = compute_scores("int main(){return 0;}", "int main(){return 0;}", "cpp")
    assert scores == {"L1": 1.0, "L2": 1.0, "L3": 1.0, "md5_ws_equal": True}
    tokens = {"u1": ["a", "b", "c", "d"], "u2": ["a", "b", "c", "d"]}
    rare = build_rare_sets(tokens, size=2, rare_threshold=3)
    assert rare_between(rare["u1"], rare["u2"]) == {
        "shared": 3,
        "score": 1.0,
        "samples": ["a b", "b c", "c d"],
    }
    common = build_rare_sets({f"u{i}": ["a", "b"] for i in range(4)}, size=2, rare_threshold=3)
    assert common["u0"] == set()


def test_template_counts_people_with_identical_code():
    counts = crowd_counts({"a": SAME, "b": SAME.replace(";", " ; "), "c": "other"})
    assert counts == {"a": 2, "b": 2, "c": 1}


def test_timeline_vector():
    result = analyze_timeline(
        [sub("u1", sid="a1", when=1000)],
        [
            sub("u2", sid="b1", when=1100, verdict="Wrong Answer"),
            sub("u2", sid="b2", when=1200),
        ],
    )
    assert result == {
        "who_first": "A",
        "delta_seconds": 0.2,
        "first_submit_delta": 0.1,
        "later_failures_before_ac": 1,
        "direction_valid": True,
        "error_types": ["答案错误"],
    }


def test_classification_rule_table():
    t = DEFAULT_THRESHOLDS
    timeline = {"direction_valid": True, "delta_seconds": 100}
    equal = {"L2": 1.0, "L3": 1.0, "md5_ws_equal": True}
    assert classify(equal, {"score": 1.0}, timeline, t, crowd_count=2) == "实锤"
    assert classify(equal, {"score": 1.0}, timeline, t, crowd_count=5) == "排除"
    assert classify(equal, {"score": 1.0}, {}, t, crowd_count=1) == "中偏强"
    assert classify({"L2": 0.9, "L3": 0.9}, {"score": 0.6}, {}, t, 1) == "中偏强"
    assert classify({"L2": 0.7, "L3": 0.82}, {"score": 0.4}, {}, t, 1) == "存疑"
    assert classify({"L2": 0.5, "L3": 0.6}, {"score": 0.1}, {}, t, 1) == "排除"
    strict = {key: 0.99 for key in t} | {"solid_delta_seconds": 1800, "crowd_threshold": 3}
    assert classify({"L2": 0.9, "L3": 0.91}, {"score": 0.7}, {}, strict) == "排除"


def test_engine_golden_result():
    code = "int main(){return 0;}"
    rows = analyze([sub("u1", code, 1000), sub("u2", code, 1200)])
    assert len(rows) == 1
    row = rows[0]
    assert row["pair"] == ["u1", "u2"]
    assert row["verdict"] == "实锤"
    assert row["similarity"] == 1.0
    assert row["scores"] == {"L1": 1.0, "L2": 1.0, "L3": 1.0, "md5_ws_equal": True}
    assert row["timeline"]["who_first"] == "A"
    assert row["timeline"]["direction_valid"] is True
    assert row["timeline"]["delta_seconds"] == 0.2
    assert row["crowd_count"] == 2
    assert "检测分级：实锤（仅供人工复核）" in row["reasons"]


def test_engine_is_order_independent_and_groups_by_problem_and_language():
    sample = [
        sub("u2", when=2000),
        sub("u1", when=1000),
        sub("u3", problem=1),
        sub("u4", language="python"),
    ]
    assert analyze(sample) == analyze(list(reversed(sample)))
    assert [row["pair"] for row in analyze(sample)] == [["u1", "u2"]]


def test_crowd_template_is_excluded():
    rows = analyze([sub("a", when=1000), sub("b", when=2000), sub("c", when=3000)])
    assert rows and all(row["verdict"] == "排除" for row in rows)
    rows = analyze(
        [sub("a", when=1000), sub("b", when=2000), sub("c", when=3000)],
        EngineConfig(enable_template=False),
    )
    assert all(row["verdict"] == "实锤" for row in rows)


def _random_code(rng, lines=30):
    words = ["for", "int", "i", "=", "0", ";", "<", "n", "++", "{", "}", "a", "[", "]", "+="]
    return "\n".join(" ".join(rng.choice(words) for _ in range(10)) for _ in range(lines))


def test_prefilter_matches_full_comparison_filtered_by_threshold():
    """初筛只省去计算，不改变结果：等价于阈值 0 的全量结果再按指纹阈值过滤。"""
    rng = random.Random(7)
    base = _random_code(rng)
    sample = [sub(f"u{i}", base if i % 3 == 0 else _random_code(rng)) for i in range(18)]
    sample += [sub("copy", base.replace("i", "j"))]
    full = analyze(sample, EngineConfig(threshold=0.0))
    filtered = [row for row in full if row["similarity"] >= 0.5]
    assert analyze(sample, EngineConfig(threshold=0.5)) == filtered
    assert filtered


def test_large_contest_finishes_quickly():
    rng = random.Random(1)
    sample = [sub(f"u{i}", _random_code(rng, 40)) for i in range(300)]
    started = time.perf_counter()
    analyze(sample)
    assert time.perf_counter() - started < 15
