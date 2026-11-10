"""
Module: Test / editable settings batch E
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


def test_multi_rules_add_remove_disable_and_reload(tmp_path):
    config = tmp_path / "config.toml"
    save_config({"contest_filter": {
        "whitelist": [{"pattern": "练习", "enabled": True},
                      {"pattern": "模拟", "enabled": False}],
        "blacklist": [{"pattern": "禁止", "enabled": True}],
        "match_field": "name",
    }}, config)
    model = SettingsModel(config, [], db_path=tmp_path / "absent.sqlite")
    assert len(model.lists.rules["whitelist"]) == 2
    model.add_list_item("比赛筛选", "blacklist")
    model.change(by_key(model, "contest_filter.blacklist.1.pattern"), "测试.*")
    model.change(by_key(model, "contest_filter.whitelist.1.enabled"), True)
    model.save()
    reloaded = SettingsModel(config, [], db_path=tmp_path / "absent.sqlite")
    assert len(reloaded.lists.rules["blacklist"]) == 2
    assert reloaded.lists.rules["whitelist"][1]["enabled"] is True
    filt = load_contest_filter(config)
    assert not evaluate_contest(Contest("synthetic", "1", "练习禁止"), filt).visible
    assert evaluate_contest(Contest("synthetic", "2", "模拟比赛"), filt).visible
    reloaded.remove_list_item(by_key(reloaded, "contest_filter.blacklist.0.pattern"))
    reloaded.save()
    assert len(load_config(config)["contest_filter"]["blacklist"]) == 1


def test_rule_blank_rejected_without_writing(tmp_path):
    config = tmp_path / "config.toml"
    model = SettingsModel(config, [], db_path=tmp_path / "absent.sqlite")
    model.add_list_item("比赛筛选", "whitelist")
    with pytest.raises(ValueError, match="不能为空"):
        model.save()
    assert not config.exists()


def test_manager_name_enabled_round_trip(tmp_path):
    db = tmp_path / "synthetic.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "101", "虚构比赛")
    config = tmp_path / "config.toml"
    model = SettingsModel(config, [], db_path=db)
    model.change(by_key(model, "people.platform"), "synthetic")
    model.save()
    model.add_list_item("人员名单")
    model.change(by_key(model, "people.manager_entries.0.uid"), "synthetic-uid")
    model.change(by_key(model, "people.manager_entries.0.nickname"), "虚构管理员")
    model.save()
    with Store(db) as store:
        rows = store.list_hidden_people()
    assert len(rows) == 1
    assert rows[0]["nickname"] == "虚构管理员"
    reloaded = SettingsModel(config, [], db_path=db)
    reloaded.change(by_key(reloaded, "people.manager_entries.0.enabled"), False)
    reloaded.save()
    with Store(db) as store:
        assert store.list_hidden_people() == []
    again = SettingsModel(config, [], db_path=db)
    assert again.lists.managers[0]["nickname"] == "虚构管理员"
    assert again.lists.managers[0]["enabled"] is False


def test_collect_settings_are_consumed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_config({"collect": {
        "phase": "contest",
        "include_after": True,
        "threads": 3,
        "retry_count": 1,
        "readonly": True,
        "auto_analyze": False,
    }})
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
def test_invalid_contest_no_output(tmp_path, command):
    output = tmp_path / "should-not-exist.md"
    arguments = ["--db", str(tmp_path / "fixture.sqlite")]
    if command == "rank":
        arguments += ["rank", "404", "--platform", "synthetic", "--output", str(output)]
    else:
        arguments += ["export", "synthetic", "404", "--output", str(output), "--format", "md"]
    with pytest.raises(ValueError, match="比赛不存在"):
        main(arguments)
    assert not output.exists()
