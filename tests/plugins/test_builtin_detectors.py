"""
Module: Builtin Detector Tests
Description: 验证内置 pair、single 与 classifier 的确定性输出。
Scope: Test
"""

from ojaudit.core.schema import Submission
from ojaudit.plugins.detectors.classifier import classify
from ojaudit.plugins.detectors.pair import analyze_pair, winnow
from ojaudit.plugins.detectors.single import analyze_single, code_metrics


def _submission(uid: str, code: str, stamp: int) -> Submission:
    return Submission(
        "synthetic",
        "demo",
        f"{uid}-{stamp}",
        uid,
        0,
        "cpp",
        "Accepted",
        100.0,
        stamp,
        "contest",
        code,
    )


def test_pair_and_classifier_are_order_independent():
    sample = [
        _submission("u2", "int main(){return value+2;}", 200),
        _submission("u1", "int main(){return value+2;}", 100),
    ]
    first = classify(analyze_pair(sample))
    second = classify(analyze_pair(reversed(sample)))
    assert first == second
    assert first[0]["pair"] == ["u1", "u2"]


def test_winnow_is_stable_and_validates_parameters():
    assert winnow("int main(){return 0;}") == winnow("int main(){return 0;}")
    try:
        winnow("abc", k=0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid k must fail")


def test_single_metrics_are_deterministic():
    code = "int main() {\n  // note\n  return 0;\n}\n"
    assert code_metrics(code) == {"loc": 3, "comments": 1, "blanks": 0, "comment_ratio": 0.25}
    sample = [_submission("u1", code, 100)]
    assert analyze_single(sample) == analyze_single(list(reversed(sample)))
