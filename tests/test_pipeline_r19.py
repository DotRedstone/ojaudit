"""合成检测数据回归：模板排除、时间线、阈值与不存在比赛。"""

import pytest

from ojaudit.cli import _analyze
from ojaudit.core.schema import Submission
from ojaudit.core.store import Store
from ojaudit.plugins.detectors.classify import classify
from ojaudit.plugins.detectors.nowcoder import analyze


def sample(uid, sid, when):
    return Submission(
        "synthetic",
        "c1",
        sid,
        uid,
        0,
        "cpp",
        "Accepted",
        100,
        when,
        "contest",
        "int main(){int value=1;return value+1;}",
    )


def test_crowd_template_is_excluded():
    results = analyze([sample("a", "1", 1000), sample("b", "2", 2000), sample("c", "3", 3000)], {})
    assert results
    assert all(item["verdict"] == "排除" for item in results)


def test_timeline_is_explained():
    result = analyze([sample("a", "1", 1000), sample("b", "2", 2000)], {})[0]
    assert "delta_seconds" in result["timeline"]
    assert "direction_valid" in result["timeline"]


def test_configurable_thresholds():
    scores = {"L2": 0.9, "L3": 0.91, "md5_ws_equal": False}
    rare = {"score": 0.7}
    strict = {
        "solid_l2": 0.99,
        "solid_delta_seconds": 1800,
        "mid_strong_rare": 0.99,
        "mid_strong_l3": 0.99,
        "suspicious_l3": 0.99,
        "suspicious_rare": 0.99,
        "crowd_threshold": 3,
    }
    assert classify(scores, rare, {}, strict) == "排除"
    permissive = {**strict, "suspicious_l3": 0.8, "suspicious_rare": 0.3}
    assert classify(scores, rare, {}, permissive) == "存疑"


def test_missing_contest_does_not_write_run(tmp_path):
    with Store(tmp_path / "missing.sqlite") as store:
        with pytest.raises(ValueError, match="比赛不存在"):
            _analyze(store, "synthetic", "none", 0.5)
        assert store.execute("SELECT count(*) FROM analysis_runs").fetchone()[0] == 0
