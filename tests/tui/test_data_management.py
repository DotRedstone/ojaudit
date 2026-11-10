"""
Module: Test / TUI data management
Description: 一键剔除比赛（首页 / 比赛列表）、设置保存不丢失剔除项、导出导入配置、删除比赛数据。
Scope: Test
Notes: 只使用合成比赛与临时配置目录，不访问网络。
"""

from __future__ import annotations

import asyncio
import json

from textual.widgets import ListView

from ojaudit.core.config import load_config, save_config
from ojaudit.core.filters import load_contest_filter
from ojaudit.core.schema import Contest, Participant, Submission
from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.screens import ContestListScreen
from ojaudit.tui.settings_model import CATEGORIES, SettingsModel


def _db(tmp_path):
    db = tmp_path / "d.sqlite"
    with Store(db) as store:
        for cid, name, start in (("1", "正式赛", 2000), ("2", "新生练习", 1000)):
            store.import_contest(
                Contest("nowcoder", cid, name, start),
                [Participant("nowcoder", cid, "u", "甲"), Participant("nowcoder", cid, "v", "乙")],
                submissions=[
                    Submission(
                        "nowcoder", cid, f"s{cid}", "u", 0, "cpp", "AC", 100, 1, "contest", "x"
                    )
                ],
            )
        store.save_analysis(
            "run2",
            "nowcoder",
            "2",
            "x",
            "test",
            "2026-01-01",
            [{"uid_a": "u", "uid_b": "v", "problem_index": 0, "language": "cpp", "level": "存疑"}],
        )
        store.put_person_mark("nowcoder", "2", "u", "suspect", "", "2026")
    return db


def test_exclude_from_home_hides_contest_and_its_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    save_config({"appearance": {"theme": "auto"}})
    db = _db(tmp_path)

    async def scenario():
        app = AuditApp(LocalContests(db))
        async with app.run_test(size=(140, 36)) as pilot:
            await pilot.pause()
            home = app.screen
            names = [entry.contest.name for entry in home.recent]
            assert names == ["正式赛", "新生练习"]
            assert home.queue, "新生练习有待复核线索"
            home.query_one("#recent", ListView).index = 1
            await pilot.press("d")
            await pilot.pause()
            assert [entry.contest.name for entry in home.recent] == ["正式赛"]
            assert not home.queue, "剔除的比赛不进待复核"
            assert load_config()["appearance"]["theme"] == "auto", "其他配置保留"
            assert load_contest_filter().excluded == ("nowcoder/2",)

            await pilot.press("1")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ContestListScreen)
            await pilot.press("a")
            await pilot.pause()
            screen.query_one("#items", ListView).index = [
                row.contest.contest_id for row in screen.rows
            ].index("2")
            await pilot.press("d")
            await pilot.pause()
            assert load_contest_filter().excluded == ()

    asyncio.run(scenario())


def test_settings_save_keeps_excluded_and_can_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db = _db(tmp_path)
    LocalContests(db).toggle_excluded(Contest("nowcoder", "2", "新生练习"))
    model = SettingsModel(db_path=db)
    rows = model.options_for("过滤规则")
    excluded = next(option for option in rows if option.kind == "excluded")
    assert excluded.title == "新生练习"
    model.values["contest_filter.case_sensitive"] = True
    model.save()
    assert load_contest_filter().excluded == ("nowcoder/2",), "保存其他设置不丢剔除项"
    model.remove(next(o for o in model.options_for("过滤规则") if o.kind == "excluded"))
    model.save()
    assert load_contest_filter().excluded == ()


def test_export_import_roundtrip_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db = _db(tmp_path)
    save_config({"collect": {"threads": 12}, "nowcoder": {"uid": "42", "cookie": "t=secret"}})
    with Store(db) as store:
        store.put_hidden_person("nowcoder", "m1", "老师")
    model = SettingsModel(db_path=db)
    exported = model.export_config(tmp_path / "out.toml")
    text = exported.read_text(encoding="utf-8")
    assert "secret" not in text and "threads = 12" in text and "m1" in text

    save_config({"collect": {"threads": 3}})
    with Store(db) as store:
        store.remove_hidden_person("nowcoder", "m1")
        store.put_hidden_person("nowcoder", "other", "")
    model = SettingsModel(db_path=db)
    model.import_config(exported)
    assert load_config()["collect"]["threads"] == 12
    assert "managers" not in load_config()
    assert [row["uid"] for row in model.managers] == ["m1"]
    bad = tmp_path / "bad.toml"
    bad.write_text("[contest_filter]\nrules = [{ pattern = '(' }]\n", encoding="utf-8")
    try:
        model.read_import(bad)
    except ValueError as exc:
        assert "过滤规则无效" in str(exc)
    else:
        raise AssertionError("无效正则应被拒绝")


def test_delete_contest_data_from_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db = _db(tmp_path)
    model = SettingsModel(db_path=db)
    rows = [o for o in model.options_for("数据") if o.kind == "contest"]
    assert [o.title for o in rows] == ["新生练习", "正式赛"]
    assert model.value(rows[0]) == (1, 1)

    async def scenario():
        from ojaudit.tui.popup import ConfirmPopup
        from ojaudit.tui.settings_screen import SettingsScreen

        app = AuditApp(LocalContests(db))
        async with app.run_test(size=(120, 34)) as pilot:
            app.push_screen(SettingsScreen(model))
            await pilot.pause()
            screen = app.screen
            screen.query_one("#categories", ListView).index = CATEGORIES.index("数据")
            await pilot.pause()
            await pilot.press("tab")
            values = screen.query_one("#settings-values", ListView)
            values.index = [o.key for o in screen.rows].index(rows[0].key)
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmPopup)
            await pilot.press("y")
            await pilot.pause()

    asyncio.run(scenario())
    with Store(db) as store:
        tables = ("contests", "submissions", "participants", "analysis_runs", "person_marks")
        left = {
            table: store.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE contest_id='2'"
            ).fetchone()[0]
            for table in tables
        }
        assert set(left.values()) == {0}, json.dumps(left)
        assert store.connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 0
        assert store.contest_exists("nowcoder", "1"), "其他比赛不受影响"
