# ruff: noqa: I001
"""
Module: Legacy Detector Migration Tests
Description: 用合成向量核对五个迁移算法模块的既有规则。
Scope: Test
"""

from ojaudit.core.schema import Submission
from ojaudit.plugins.detectors import classify, normalize, similarity, template, timeline


THRESHOLDS = {
    "solid_l2": 0.98,
    "solid_delta_seconds": 1800,
    "mid_strong_rare": 0.5,
    "mid_strong_l3": 0.85,
    "suspicious_l3": 0.8,
    "suspicious_rare": 0.3,
    "crowd_threshold": 3,
}


def test_normalize_matches_legacy_synthetic_vector():
    value = normalize.normalize("int add(int x) { return x + 1; }", "cpp")
    assert value["L1"] == "int add(int x) { return x + 1; }"
    assert value["L2"] == "intadd(intx){returnx+1;}"
    assert value["L3"] == [
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


def test_similarity_matches_legacy_synthetic_vector():
    scores = similarity.compute_scores("int main(){return 0;}", "int main(){return 0;}", "cpp")
    assert scores == {"L1": 1.0, "L2": 1.0, "L3": 1.0, "md5_ws_equal": True}
    tokens = {"u1": ["a", "b", "c", "d"], "u2": ["a", "b", "c", "d"]}
    rare = similarity.build_rare_sets(tokens, size=2, rare_threshold=3)
    assert similarity.rare_between(rare["u1"], rare["u2"]) == {
        "shared": 3,
        "score": 1.0,
        "samples": ["a b", "b c", "c d"],
    }


def test_template_matches_legacy_crowd_and_common_ratio_rules():
    tokens = ["a", "b", "c", "d"]
    usage = template.build_usage({f"u{i}": tokens for i in range(4)}, size=2)
    assert template.common_ratio(tokens, usage, size=2, rare_threshold=3) == 1.0
    codes = {f"u{i}": "int main(){return 0;}" for i in range(3)}
    assert template.crowd_count(codes, "u1") == 3
    assert template.exclude_crowd_template(codes, "u2", threshold=3)


def test_timeline_matches_legacy_synthetic_vector():
    def sub(uid, sid, verdict, timestamp):
        return Submission(
            "synthetic",
            "demo",
            sid,
            uid,
            0,
            "cpp",
            verdict,
            100,
            timestamp,
            "contest",
            "int main(){return 0;}",
        )

    result = timeline.analyze_timeline(
        [sub("u1", "a1", "Accepted", 1000)],
        [sub("u2", "b1", "Wrong Answer", 1100), sub("u2", "b2", "Accepted", 1200)],
    )
    assert result == {
        "who_first": "A",
        "delta_seconds": 0.2,
        "first_submit_delta": 0.1,
        "later_failures_before_ac": 1,
        "direction_valid": True,
        "error_types": ["答案错误"],
    }


def test_classifier_matches_original_rule_table():
    assert (
        classify.classify(
            {"L2": 1.0, "L3": 1.0, "md5_ws_equal": True},
            {"score": 1.0},
            {"direction_valid": True, "delta_seconds": 100},
            THRESHOLDS,
            crowd_count=2,
        )
        == "实锤"
    )
    assert (
        classify.classify(
            {"L2": 1.0, "L3": 1.0, "md5_ws_equal": True},
            {"score": 1.0},
            {"direction_valid": True, "delta_seconds": 100},
            THRESHOLDS,
            crowd_count=5,
        )
        == "排除"
    )
    assert classify.classify({"L2": 0.9, "L3": 0.9}, {"score": 0.6}, {}, THRESHOLDS, 1) == "中偏强"
    assert classify.classify({"L2": 0.7, "L3": 0.82}, {"score": 0.4}, {}, THRESHOLDS, 1) == "存疑"
    assert classify.classify({"L2": 0.5, "L3": 0.6}, {"score": 0.1}, {}, THRESHOLDS, 1) == "排除"
