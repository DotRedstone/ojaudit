"""
Module: Test / TUI keyboard and mouse
Description: 用 Pilot 检查方向键、列表单击/双击和弹窗取消。
Scope: Test
Notes: 仅合成数据库与临时配置，不包含真实比赛或登录信息。
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input, ListView

from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.review_screens import ChoiceDialog
from ojaudit.tui.screens import ContestListScreen, ContestOverviewScreen, EntryDialog, HomeScreen
from ojaudit.tui.settings_model import SettingsModel
from ojaudit.tui.settings_screen import ConfirmLeave, EditValue, SettingsScreen


def test_empty_home_focus_and_navigation(tmp_path):
    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            view = app.screen.query_one(ListView)
            assert app.focused is view
            assert "ojaudit login" in str(app.screen.query_one("#empty-guide").render())
            await pilot.press("right")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            assert not app.screen.entries
            assert "ojaudit collect" in str(
                app.screen.query_one(ListView).children[0].query_one("Label").render()
            )
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("j", "k", "shift+g", "g")
            assert app.screen.query_one(ListView).index == 0
            await pilot.press("space")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            await pilot.press("left")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())


def test_mouse_single_then_double_click(tmp_path):
    db = tmp_path / "demo.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "101", "虚构比赛")

    async def scenario():
        app = AuditApp(LocalContests(db))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.click("HomeScreen ListItem", offset=(2, 0))
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.double_click("HomeScreen ListItem", offset=(2, 0))
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ContestOverviewScreen)
            await pilot.click("#breadcrumb", offset=(2, 0))
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)

    asyncio.run(scenario())


def test_entry_dialog_esc_and_enter(tmp_path):
    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            app.screen.query_one(ListView).index = 1
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EntryDialog)
            assert isinstance(app.focused, Input)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            app.screen.query_one(ListView).index = 1
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EntryDialog)
            await pilot.click("#entry-cancel")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())


def test_choice_dialog_and_settings_confirmation(tmp_path):
    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            app.push_screen(ChoiceDialog("虚构结论", (("正常", "normal"), ("存疑", "suspect"))))
            await pilot.pause()
            assert isinstance(app.screen, ChoiceDialog)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

            model = SettingsModel(tmp_path / "config.toml", [])
            app.push_screen(SettingsScreen(model))
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            await pilot.press("l")
            assert app.screen.focus_values
            await pilot.press("j", "k", "space")
            await pilot.press("h")
            assert not app.screen.focus_values
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

            app.push_screen(ConfirmLeave())
            await pilot.pause()
            assert app.focused is app.screen.query_one("#stay")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())


def test_edit_value_esc_from_input(tmp_path):
    model = SettingsModel(tmp_path / "config.toml", [])
    option = next(o for o in model.options if o.kind == "text" and not o.readonly)

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "empty.sqlite"))
        async with app.run_test() as pilot:
            app.push_screen(EditValue(option, "synthetic"))
            await pilot.pause()
            assert isinstance(app.focused, Input)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())
