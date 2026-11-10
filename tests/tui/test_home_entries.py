"""
Module: Test / TUI home entries
Description: 首页打开比赛 ID、账户入口与未采集比赛引导。
Scope: Test
Notes: 只使用合成数据。
"""

import asyncio
import stat

from textual.widgets import Input, ListView

from ojaudit.core.store import Store
from ojaudit.tui.account_screen import AccountScreen
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.screens import ContestOverviewScreen, EntryDialog, HomeScreen, MissingContestScreen


def test_open_local_contest_by_id(tmp_path):
    db = tmp_path / "demo.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "101", "虚构比赛")

    async def scenario():
        app = AuditApp(LocalContests(db))
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HomeScreen)
            app.screen.query_one(ListView).index = 1
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EntryDialog)
            app.screen.query_one(Input).value = "101"
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ContestOverviewScreen)
            assert app.screen.contest.contest_id == "101"

    asyncio.run(scenario())


def test_missing_contest_shows_actionable_path(tmp_path):
    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "missing.sqlite"))
        async with app.run_test() as pilot:
            app.screen.query_one(ListView).index = 1
            await pilot.press("enter")
            await pilot.pause()
            app.screen.query_one(Input).value = "999"
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, MissingContestScreen)
            assert app.screen.contest_id == "999"
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())


def test_login_masked_and_mode_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "missing.sqlite"))
        async with app.run_test() as pilot:
            app.screen.query_one(ListView).index = 2
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, AccountScreen)
            app.screen.query_one(ListView).index = 2
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EntryDialog)
            field = app.screen.query_one(Input)
            assert field.password is True
            field.value = "synthetic_cookie=not_real"
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, AccountScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)

    asyncio.run(scenario())
    path = tmp_path / "ojaudit" / "nowcoder.cookie"
    assert path.read_text(encoding="utf-8") == "synthetic_cookie=not_real"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
