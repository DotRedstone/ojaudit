"""
Module: Nowcoder Detector Tests
Description: 验证迁移的确定性相似度规则。
Scope: Test
"""

from ojaudit.core.schema import Submission
from ojaudit.plugins.detectors.nowcoder import analyze, normalize_tokens


def _submission(uid: str, code: str, when: int) -> Submission:
    return Submission(
        platform="synthetic",
        contest_id="demo",
        submission_id=f"{uid}-{when}",
        uid=uid,
        problem_index=0,
        language="cpp",
        verdict="Accepted",
        score=100,
        submit_time=when,
        phase="contest",
        code=code,
    )


def test_identifier_renaming_normalizes_to_same_tokens():
    assert normalize_tokens("int sum(int a){return a+1;}", "cpp") == normalize_tokens(
        "int calc(int value){return value+9;}", "cpp"
    )


def test_pair_analysis_is_deterministic_and_sorted():
    submissions = [
        _submission("u2", "int f(){return 7;}", 2000),
        _submission("u1", "int f(){return 7;}", 1000),
    ]
    first = analyze(submissions)
    second = analyze(list(reversed(submissions)))
    assert first == second
    assert first[0]["pair"] == ["u1", "u2"]
    assert first[0]["scores"]["md5_ws_equal"] is True


def test_cross_problem_or_language_pairs_are_not_compared():
    left = _submission("u1", "int main(){return 0;}", 1000)
    right = _submission("u2", "int main(){return 0;}", 2000)
    assert analyze([left, right]) == analyze([right, left])
