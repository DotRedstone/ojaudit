"""
Module: Test / core analysis
Description: 验证分析流程的配置优先级、参数校验、管理者排除与写库。
Scope: Test
Notes: 只使用合成数据。
"""

import pytest

from ojaudit.core.analysis import engine_config, run_analysis
from ojaudit.core.schema import Contest, Submission
from ojaudit.core.store import Store

CODE = "int main(){int value=1;return value+1;}"


def _store(path, uids=("a", "b")):
    store = Store(path)
    store.import_contest(
        Contest("synthetic", "c1", "合成"),
        submissions=[
            Submission(
                "synthetic",
                "c1",
                f"s{i}",
                uid,
                0,
                "cpp",
                "AC",
                100,
                1000 * (i + 1),
                "contest",
                CODE,
            )
            for i, uid in enumerate(uids)
        ],
    )
    return store


def test_config_precedence_and_stale_keys_are_ignored():
    settings = {
        "plugins": {
            "builtin_pair": {"params": {"threshold": 0.7}},
            "nowcoder_template": {"enabled": False, "params": {"ngram_size": 9}},
        }
    }
    config, active = engine_config(settings)
    assert config.threshold == 0.7
    assert not config.enable_template
    assert "nowcoder_template" not in active
    assert engine_config(settings, threshold=0.2)[0].threshold == 0.2
    assert engine_config({})[0].threshold == 0.5


def test_invalid_or_disabled_settings_fail_clearly():
    with pytest.raises(ValueError, match="禁用"):
        engine_config({"detector": {"enabled": False}})
    _config, active = engine_config({"plugins": {"builtin_pair": {"enabled": False}}})
    assert "builtin_pair" in active
    with pytest.raises(ValueError):
        engine_config({"plugins": {"builtin_pair": {"params": {"threshold": 2}}}})


def test_run_writes_findings_and_skips_hidden_people(tmp_path):
    with _store(tmp_path / "s.sqlite", ("a", "b", "boss")) as store:
        store.put_hidden_person("synthetic", "boss")
        result = run_analysis(store, "synthetic", "c1", settings={})
        assert [row["pair"] for row in result.findings] == [["a", "b"]]
        stored = store.execute("SELECT uid_a, uid_b, verdict_level FROM findings").fetchall()
        assert [tuple(row) for row in stored] == [("a", "b", "实锤")]


def test_missing_contest_does_not_write_run(tmp_path):
    with Store(tmp_path / "missing.sqlite") as store:
        with pytest.raises(ValueError, match="比赛不存在"):
            run_analysis(store, "synthetic", "none", settings={})
        assert store.execute("SELECT count(*) FROM analysis_runs").fetchone()[0] == 0
