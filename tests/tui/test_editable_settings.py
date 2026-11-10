"""
Module: Test / editable settings
Description: Synthetic list editing, persistence, collection settings and unknown ranking.
Scope: Test
Notes: No live source requests, credentials or real participant IDs.
"""

from __future__ import annotations

import pytest

from ojaudit.cli import main
from ojaudit.cli_operations import nowcoder_source
from ojaudit.core.config import load_config, save_config
from ojaudit.core.filters import evaluate_contest, load_contest_filter
from ojaudit.core.schema import Contest
from ojaudit.core.store import Store
from ojaudit.plugins.sources.nowcoder import NowcoderSource
from ojaudit.tui.settings_model import SettingsModel


def by_key(model, key):
    return next(option for option in model.options if option.key == key)


def test_filter_rules_add_edit_toggle_remove_and_reload(tmp_path):
    db = tmp_path / "synthetic.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "1", "练习禁止")
        store.put_contest("synthetic", "2", "模拟比赛")
    config = tmp_path / "config.toml"
    save_config({"contest_filter": {"blacklist": [{"pattern": "旧规则"}]}}, config)
    model = SettingsModel(config, [], db_path=db)
    assert model.values["contest_filter.mode"] == "blacklist"
    assert [r["pattern"] for r in model.rules] == ["旧规则"]
    model.set_rule(0, "禁止")
    model.set_rule(None, "^模拟")
    assert model.rule_hits("禁止") == 1
    model.toggle_rule(1)
    assert model.dirty
    model.save()
    assert not model.dirty
    filt = load_contest_filter(config)
    assert not evaluate_contest(Contest("synthetic", "1", "练习禁止"), filt).visible
    assert evaluate_contest(Contest("synthetic", "2", "模拟比赛"), filt).visible
    assert "whitelist" not in load_config(config)["contest_filter"]

    reloaded = SettingsModel(config, [], db_path=db)
    mode = by_key(reloaded, "contest_filter.mode")
    reloaded.change(mode, "whitelist")
    reloaded.toggle_rule(1)
    reloaded.remove(by_key(reloaded, "rules.0"))
    reloaded.save()
    filt = load_contest_filter(config)
    assert filt.mode == "whitelist"
    assert [r.pattern for r in filt.rules] == ["^模拟"]
    assert not evaluate_contest(Contest("synthetic", "1", "练习禁止"), filt).visible


def test_invalid_rules_are_rejected_before_writing(tmp_path):
    config = tmp_path / "config.toml"
    model = SettingsModel(config, [], db_path=tmp_path / "absent.sqlite")
    with pytest.raises(ValueError, match="不能为空"):
        model.set_rule(None, "")
    with pytest.raises(ValueError, match="正则无效"):
        model.set_rule(None, "[")
    assert model.rules == []
    assert not config.exists()


def test_managers_round_trip_through_database(tmp_path):
    db = tmp_path / "synthetic.sqlite"
    with Store(db):
        pass
    config = tmp_path / "config.toml"
    model = SettingsModel(config, [], db_path=db)
    model.set_manager(None, "1001 虚构 管理员")
    with pytest.raises(ValueError, match="已存在"):
        model.set_manager(None, "1001")
    model.save()
    with Store(db) as store:
        assert store.list_hidden_people() == [
            {"platform": "nowcoder", "uid": "1001", "nickname": "虚构 管理员"}
        ]
    reloaded = SettingsModel(config, [], db_path=db)
    reloaded.set_manager(0, "1002")
    reloaded.save()
    with Store(db) as store:
        assert [row["uid"] for row in store.list_hidden_people()] == ["1002"]
    again = SettingsModel(config, [], db_path=db)
    again.remove(by_key(again, "managers.0"))
    again.save()
    with Store(db) as store:
        assert store.list_hidden_people() == []


def test_collect_settings_are_consumed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_config(
        {
            "collect": {
                "phase": "contest",
                "include_after": True,
                "threads": 3,
                "retry_count": 1,
                "readonly": True,
                "auto_analyze": False,
            }
        }
    )
    source = nowcoder_source()
    assert source.config["phase"] == "all"
    assert source.config["threads"] == 3
    assert source.config["retry_count"] == 1

    class FakeResponse:
        def read(self):
            return b"ok"

    attempts = []

    def flaky(request, timeout):
        attempts.append(request.full_url)
        if len(attempts) == 1:
            raise OSError("synthetic intermittent failure")
        return FakeResponse()

    offline = NowcoderSource({"retry_count": 1}, opener=flaky)
    assert offline._get("https://example.invalid/fixture", "fake-cookie") == "ok"
    assert len(attempts) == 2
    with pytest.raises(ValueError, match="只读"):
        NowcoderSource({"readonly": False}).fetch_contest(None, "101")


@pytest.mark.parametrize("command", ["rank", "export"])
def test_invalid_contest_no_output(tmp_path, command, capsys):
    output = tmp_path / "should-not-exist.md"
    arguments = ["--db", str(tmp_path / "fixture.sqlite")]
    if command == "rank":
        arguments += ["rank", "404", "--platform", "synthetic", "--output", str(output)]
    else:
        arguments += ["export", "synthetic", "404", "--output", str(output), "--format", "md"]
    with pytest.raises(SystemExit) as exit_info:
        main(arguments)
    assert exit_info.value.code == 1
    assert "比赛不存在" in capsys.readouterr().err
    assert not output.exists()
