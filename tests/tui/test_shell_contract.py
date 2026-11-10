"""
Module: Test / TUI shell contract
Description: 验证所有全屏页面共用顶栏与提示栏、无 Footer/命令面板，以及弹窗尺寸与 Esc 取消。
Scope: Test
Notes: 仅使用合成数据；截图写入 pytest 临时目录。
"""

from __future__ import annotations

import asyncio

from textual.widgets import Footer, Static

from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.ranking_screen import RankingScreen
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.review_screens import FindingsScreen, PeopleScreen, ProblemsScreen, ReviewPopup
from ojaudit.tui.screens import (
    ContestListScreen,
    ContestOverviewScreen,
    EntryDialog,
    HomeScreen,
    MissingContestScreen,
)
from ojaudit.tui.settings_screen import ConfirmLeave, EditValue, SettingsScreen


def test_every_page_has_shell_and_no_footer(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db = tmp_path / "synthetic.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "101", "虚构练习赛")

    async def scenario():
        from ojaudit.tui.account_screen import AccountScreen
        from ojaudit.tui.pending_screen import PendingScreen

        app = AuditApp(LocalContests(db))
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            contest = app.contests.list_contests(show_all=True)[0].contest
            data = ReviewData(app.contests, contest)
            pages = (
                None,
                ContestListScreen(app.contests),
                ContestOverviewScreen(contest, app.contests),
                FindingsScreen(data, "首页 › 比赛列表"),
                PeopleScreen(data, "首页 › 比赛列表"),
                ProblemsScreen(data, "首页 › 比赛列表"),
                RankingScreen(data),
                SettingsScreen(),
                AccountScreen(),
                PendingScreen(),
                MissingContestScreen("404"),
            )
            for screen in pages:
                if screen is not None:
                    app.push_screen(screen)
                    await pilot.pause()
                top = str(app.screen.query_one("#frame-top", Static).render())
                bottom = str(app.screen.query_one("#status", Static).render())
                assert top.count("╭") == len(app.screen_stack) - 1, "每一层页面露出一条标题边"
                assert "帮助" in bottom
                assert not list(app.screen.query(Footer))
                assert "palette" not in app.export_screenshot()
                if screen is not None:
                    app.pop_screen()
                    await pilot.pause()

    asyncio.run(scenario())


def test_dialogs_are_compact_and_escape_cancels(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    async def scenario():
        from ojaudit.tui.account_screen import UidDialog
        from ojaudit.tui.settings_model import SettingsModel
        from ojaudit.tui.style_help import StyleHelpScreen

        app = AuditApp(LocalContests(tmp_path / "missing.sqlite"))
        model = SettingsModel(tmp_path / "settings.toml", [])
        option = model.options_for("外观")[0]
        monkeypatch.setattr("ojaudit.tui.account_screen.current_uid", lambda: "")
        dialogs = (
            UidDialog(),
            EntryDialog(),
            EditValue(option, model.values[option.key]),
            ConfirmLeave(),
            ReviewPopup("合成标记", (("正常", "normal"),)),
            StyleHelpScreen(),
        )
        async with app.run_test(size=(100, 35)) as pilot:
            for dialog in dialogs:
                app.push_screen(dialog)
                await pilot.pause()
                box = dialog.query_one(".popup")
                assert 0 < box.size.height < 30
                assert box.size.width <= 90
                await pilot.press("escape")
                await pilot.pause()
                assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())
