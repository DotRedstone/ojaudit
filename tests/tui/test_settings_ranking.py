"""
Module: Test / TUI settings and ranking
Description: 用合成配置、插件声明和比赛数据验证设置与排行榜。
Scope: Test
Notes: 所有账户及人员标识均为虚构，输出限制在临时目录。
"""

from __future__ import annotations

import asyncio

from textual.widgets import Label, ListView, Static

from ojaudit.core.config import load_config
from ojaudit.core.filters import ContestFilter, load_contest_filter
from ojaudit.core.plugins import parse_manifest
from ojaudit.core.ranking import RankingOptions
from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.ranking_data import export_ranking, final_ranking, pending_warnings
from ojaudit.tui.ranking_screen import RankingScreen
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.settings_model import CATEGORIES, SettingsModel
from ojaudit.tui.settings_screen import ConfirmLeave, SettingsScreen


def fake_manifest():
    return parse_manifest(
        """
name = "fake_detector"
kind = "detector.pair"
version = "1.0"
api_version = 1
description = "仅供测试"
[params.active]
type = "bool"
default = true
[params.mode]
type = "enum"
default = "fast"
choices = ["fast", "exact"]
[params.limit]
type = "int"
default = 3
min = 1
max = 7
[params.pattern]
type = "str"
default = "demo"
""",
        "synthetic/plugin.toml",
    )


def example(tmp_path):
    path = tmp_path / "data.sqlite3"
    with Store(path) as store:
        store.put_contest("synthetic", "demo", "虚构练习赛")
        with store.connection:
            for uid, name in (("a", "甲"), ("b", "乙"), ("c", "丙")):
                store.execute(
                    "INSERT INTO participants(platform,contest_id,uid,name) VALUES(?,?,?,?)",
                    ("synthetic", "demo", uid, name),
                )
            store.execute(
                "INSERT INTO problems(platform,contest_id,problem_index,problem_id,title)"
                " VALUES(?,?,?,?,?)",
                ("synthetic", "demo", 0, "P0", "示例题目"),
            )
            for uid, score, time in (("a", 100, 20), ("b", 90, 25), ("c", 80, 30)):
                store.execute(
                    "INSERT INTO submissions(platform,contest_id,submission_id,uid,"
                    "problem_index,language,verdict,score,submit_time,phase,code)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "synthetic",
                        "demo",
                        "s-" + uid,
                        uid,
                        0,
                        "python",
                        "AC",
                        score,
                        time,
                        "contest",
                        "print(1)",
                    ),
                )
            store.execute(
                "INSERT INTO analysis_runs(run_id,platform,contest_id,plugin_set,"
                "created_from,created_at) VALUES(?,?,?,?,?,?)",
                ("run-fake", "synthetic", "demo", "[]", "fake", "2026-01-01"),
            )
            store.execute(
                "INSERT INTO findings(run_id,uid_a,uid_b,problem_index,language,"
                "verdict_level,scores,reasons) VALUES(?,?,?,?,?,?,?,?)",
                ("run-fake", "a", "b", 0, "python", "low", "{}", "[]"),
            )
        store.put_person_mark("synthetic", "demo", "b", "cheater", updated_at="2026-01-01")
        store.put_person_mark("synthetic", "demo", "c", "suspect", updated_at="2026-01-01")
    local = LocalContests(path, ContestFilter())
    return local, ReviewData(local, local.list_contests()[0].contest)


def test_option_types_defaults_and_persistence(tmp_path):
    path = tmp_path / "config.toml"
    manifest = fake_manifest()
    model = SettingsModel(path, [manifest])
    names = {o.key: o for o in model.options}
    assert names["plugins.fake_detector.params.active"].kind == "bool"
    assert names["plugins.fake_detector.params.mode"].kind == "enum"
    assert names["plugins.fake_detector.params.limit"].kind == "int"
    assert names["plugins.fake_detector.params.pattern"].kind == "str"
    model.change(names["plugins.fake_detector.params.active"], False)
    model.change(names["plugins.fake_detector.params.mode"], "exact")
    model.change(names["plugins.fake_detector.params.limit"], 5)
    model.change(names["account.cookie_env"], "SYNTHETIC_COOKIE_ENV")
    assert model.dirty
    assert model.changed(names["plugins.fake_detector.params.limit"])
    model.restore("账户")
    assert not model.changed(names["account.cookie_env"])
    model.save()
    assert not model.dirty
    assert load_config(path)["plugins"]["fake_detector"]["params"]["limit"] == 5
    assert SettingsModel(path, [manifest]).values["plugins.fake_detector.params.mode"] == "exact"


def test_settings_pilot_controls_and_unsaved_confirm(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("OJAUDIT_THEME_FILE", str(tmp_path / "no-wallpaper.json"))
    model = SettingsModel(tmp_path / "config.toml", [fake_manifest()])

    async def scenario():
        app = AuditApp()
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen(model))
            await pilot.pause()
            screen = app.screen
            screen.query_one("#categories", ListView).index = CATEGORIES.index("外观")
            await pilot.pause()
            await pilot.press("l")
            await pilot.pause()
            before = app.theme
            await pilot.press("space", "space")
            await pilot.pause()
            assert model.dirty
            assert app.theme != before, "外观修改应立即预览"
            assert "*" in str(
                screen.query_one("#settings-values", ListView).children[0].query_one(Label).render()
            )
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmLeave)
            await pilot.press("n")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            await pilot.press("r")
            assert not model.dirty
            assert app.theme == before
            option = model.options_for("采集")[1]
            screen.apply_input(option, "12")
            screen.action_save()
            assert not model.dirty
            assert load_config(tmp_path / "config.toml")["collect"]["threads"] == 12
            await pilot.press("space")
            await pilot.press("escape", "y")
            await pilot.pause()
            assert not isinstance(app.screen, SettingsScreen)
            assert app.theme == before, "放弃修改后恢复原外观"

    asyncio.run(scenario())


def test_ranking_policy_warning_and_exports(tmp_path, monkeypatch):
    _, data = example(tmp_path)
    assert len(final_ranking(data, RankingOptions()).rows) == 2
    marked = final_ranking(data, RankingOptions(cheaters="mark", suspects="mark", managers="mark"))
    assert len(marked.rows) == 3
    assert marked.rows[1]["person_mark"] == "cheater"
    # 只提醒检测筛出的人：未标记但没有线索的选手不算待处理。
    assert pending_warnings(data) == ("仍有 1 条线索待复核（涉及 2 人）",)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    for extension in ("md", "csv", "html"):
        target = export_ranking(data, RankingOptions(), extension)
        assert target.is_file()
        assert str(target).startswith(str(tmp_path / "xdg" / "ojaudit" / "exports"))
        assert "ranking." in target.name


def test_ranking_pilot_preview_changes(tmp_path):
    local, data = example(tmp_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test() as pilot:
            app.push_screen(RankingScreen(data))
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, RankingScreen)
            assert len(final_ranking(data, screen.policy()).rows) == 2
            assert "待复核" in str(screen.query_one("#ranking-warning", Static).render())
            await pilot.press("l")
            await pilot.pause()
            assert screen.policy().cheaters == "mark"
            assert len(final_ranking(data, screen.policy()).rows) == 3
            await pilot.press("j", "l")
            assert screen.policy().suspects == "mark"
            await pilot.press("escape")

    asyncio.run(scenario())


def test_filter_rules_page_add_rule_and_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    local, _data = example(tmp_path)
    config_file = tmp_path / "settings.toml"
    model = SettingsModel(config_file, [], db_path=local.db_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen(model))
            await pilot.pause()
            screen = app.screen
            screen.query_one("#categories", ListView).index = CATEGORIES.index("过滤规则")
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            await pilot.press(*"[", "enter")
            await pilot.pause()
            assert model.rules == [], "非法正则不会被加入"
            await pilot.press("backspace", *"^虚构", "enter")
            await pilot.pause()
            assert model.rules == [{"pattern": "^虚构", "enabled": True}]
            assert model.rule_hits("^虚构") == 1
            await pilot.press("space")
            assert model.rules[0]["enabled"] is False
            await pilot.press("space")
            screen.query_one("#settings-values", ListView).index = len(screen.rows) - 1
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press(*"a 管理", "enter")
            await pilot.pause()
            assert model.managers == [{"uid": "a", "nickname": "管理"}]
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert not model.dirty

    asyncio.run(scenario())
    with Store(local.db_path) as store:
        assert [
            row["uid"] for row in store.list_hidden_people() if row["platform"] == "nowcoder"
        ] == ["a"]
    filt = load_contest_filter(config_file)
    assert (filt.mode, filt.rules[0].pattern) == ("blacklist", "^虚构")
