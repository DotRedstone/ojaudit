"""
Module: Test / TUI unified shell
Description: 使用合成数据验证全屏共用壳、状态栏、弹窗和主题状态行。
Scope: Test
Notes: 截图只存放在 pytest 临时目录，不读取真实账户与比赛数据。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.screen import ModalScreen
from textual.widgets import Footer, ListView, Static

from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.interaction import NavigateListView, SearchDialog
from ojaudit.tui.ranking_screen import RankingScreen
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.review_screens import (
    CodeScreen,
    EvidenceScreen,
    FindingsScreen,
    PeopleScreen,
    ProblemsScreen,
    ReviewListScreen,
)
from ojaudit.tui.screens import (
    ContestListScreen,
    ContestOverviewScreen,
    EntryDialog,
    HomeScreen,
    MissingContestScreen,
    ShellScreen,
)
from ojaudit.tui.settings_screen import ConfirmLeave, EditValue, SettingsScreen
from ojaudit.tui.ui_components import StatusRow, row_kind


def test_page_inheritance_and_theme_contract():
    from ojaudit.tui.account_screen import AccountScreen
    from ojaudit.tui.pending_screen import PendingScreen

    pages = (
        HomeScreen,
        ContestListScreen,
        ContestOverviewScreen,
        MissingContestScreen,
        AccountScreen,
        PendingScreen,
        ReviewListScreen,
        FindingsScreen,
        PeopleScreen,
        ProblemsScreen,
        EvidenceScreen,
        CodeScreen,
        SettingsScreen,
        RankingScreen,
    )
    assert all(issubclass(screen, ShellScreen) for screen in pages)
    assert not issubclass(ShellScreen, ModalScreen)

    css = (Path(__file__).resolve().parents[2] / "src/ojaudit/tui/themes/nowcoder.tcss")
    rules = css.read_text(encoding="utf-8")
    assert "#breadcrumb {" in rules and "height: 1;" in rules
    assert ".dialog-box {" in rules and "max-height: 20;" in rules
    assert "$accent 20%" in rules and ".status-row" in rules
    assert "Footer {" not in rules
    assert row_kind({"mark": "cheater"}) == "mark-cheater"
    assert row_kind({"verdict_level": "high"}) == "level-high"


def test_shell_status_and_synthetic_screenshots(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db = tmp_path / "synthetic.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "101", "虚构练习赛")

    async def scenario():
        from ojaudit.tui.account_screen import AccountScreen
        from ojaudit.tui.pending_screen import PendingScreen

        app = AuditApp(LocalContests(db))
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause()
            contest = app.contests.list_contests(show_all=True)[0].contest
            data = ReviewData(app.contests, contest)
            pages = (
                ("home", None),
                ("contests", ContestListScreen(app.contests)),
                ("overview", ContestOverviewScreen(contest, app.contests)),
                ("findings", FindingsScreen(data, "首页 › 比赛列表")),
                ("people", PeopleScreen(data, "首页 › 比赛列表")),
                ("problems", ProblemsScreen(data, "首页 › 比赛列表")),
                ("ranking", RankingScreen(data)),
                ("settings", SettingsScreen()),
                ("account", AccountScreen()),
                ("pending", PendingScreen()),
                ("missing", MissingContestScreen("404")),
            )
            for name, screen in pages:
                if screen is not None:
                    app.push_screen(screen)
                    await pilot.pause()
                assert isinstance(app.screen, ShellScreen)
                assert app.screen.query_one("#breadcrumb", Static)
                assert app.screen.query_one("#pane")
                status = app.screen.query_one("#status", Static)
                assert "NORMAL" in str(status.render())
                assert not list(app.screen.query(Footer))
                assert not list(app.screen.query("Footer"))
                app.save_screenshot(filename=f"{name}.svg", path=str(tmp_path))
                svg = (tmp_path / f"{name}.svg").read_text(encoding="utf-8")
                assert "NORMAL" in svg
                assert "^palette" not in svg
                if name in {"home", "contests", "overview", "settings", "ranking"}:
                    assert app.screen.query_one(ListView)
                if name == "ranking":
                    assert app.screen.query_one("#ranking-options", NavigateListView)
                    assert app.screen.query_one("#ranking-preview", NavigateListView)
                if name == "settings":
                    assert app.screen.query_one("#categories", NavigateListView)
                    assert app.screen.query_one("#settings-values", NavigateListView)
                if screen is not None:
                    app.pop_screen()
                    await pilot.pause()
            assert "" not in str(app.status_line("首页"))
            assert app.screen.query_one(ListView).children
            assert isinstance(StatusRow("示例"), StatusRow)

    asyncio.run(scenario())


def test_compact_modal_sizing_and_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    async def scenario():
        from ojaudit.tui.account_screen import UidDialog
        from ojaudit.tui.review_screens import ChoiceDialog
        from ojaudit.tui.settings_model import SettingsModel
        from ojaudit.tui.style_help import StyleHelpScreen

        app = AuditApp(LocalContests(tmp_path / "missing.sqlite"))
        model = SettingsModel(tmp_path / "settings.toml", [])
        option = model.options_for("外观")[0]
        monkeypatch.setattr("ojaudit.tui.account_screen.current_uid", lambda: "")
        dialogs = (
            SearchDialog(),
            UidDialog(),
            EntryDialog(),
            EditValue(option, model.values[option.key]),
            ConfirmLeave(),
            ChoiceDialog("合成标记", (("正常", "normal"),)),
            StyleHelpScreen(),
        )
        async with app.run_test(size=(100, 35)) as pilot:
            for dialog in dialogs:
                app.push_screen(dialog)
                await pilot.pause()
                assert dialog.query_one(".dialog-box").size.height < 25
                app.save_screenshot(filename=f"{type(dialog).__name__}.svg", path=str(tmp_path))
                await pilot.press("escape")
                await pilot.pause()
                assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())
