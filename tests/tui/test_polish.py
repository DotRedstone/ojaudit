"""
Module: Test / TUI polish
Description: 程序内扫码弹窗、可拖拽分隔条、已参加比赛同步与确认采集、外观即时生效与配置热加载、
    底部搜索行。
Scope: Test
Notes: 只使用合成数据与假登录、假数据源，不访问网络。
"""

from __future__ import annotations

import asyncio
import time

from textual.widgets import ListView, Static

from ojaudit.core.config import load_config, save_config
from ojaudit.core.schema import Contest, Submission
from ojaudit.core.store import Store
from ojaudit.tui import account_screen
from ojaudit.tui.account_screen import QrLoginScreen
from ojaudit.tui.account_service import qr_half_blocks, qr_matrix
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.popup import ConfirmPopup, SearchLine
from ojaudit.tui.screens import ContestListScreen
from ojaudit.tui.settings_model import CATEGORIES, SettingsModel
from ojaudit.tui.settings_screen import SettingsScreen
from ojaudit.tui.splitter import Splitter


def test_half_block_rendering():
    matrix = [[True, False, True], [True, True, False], [False, True, False]]
    assert qr_half_blocks(matrix) == ["█▄▀", " ▀ "]
    lines = qr_half_blocks(qr_matrix("https://weixin.qq.com/q/synthetic"))
    assert len({len(line) for line in lines}) == 1
    assert len(lines) <= len(lines[0]) // 2 + 1


def test_qr_popup_shows_code_and_saves_uid(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(account_screen, "detect_and_save_uid", lambda: "1234")

    def fake_login(status, on_qr, cancelled):
        on_qr("https://weixin.qq.com/q/synthetic")
        status("等待手机确认…")
        time.sleep(0.2)

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "none.sqlite"))
        results = []
        async with app.run_test() as pilot:
            app.push_screen(QrLoginScreen(login=fake_login), results.append)
            for _ in range(20):
                await pilot.pause(0.05)
                if isinstance(app.screen, QrLoginScreen):
                    code = str(app.screen.query_one("#qr-code", Static).render())
                    if "█" in code or "▀" in code:
                        break
            else:
                raise AssertionError("二维码没有显示在程序内")
            for _ in range(40):
                await pilot.pause(0.05)
                if results:
                    break
        assert results == [True]

    asyncio.run(scenario())


def test_qr_popup_escape_cancels_login(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    seen = []

    def waiting_login(status, on_qr, cancelled):
        on_qr("https://weixin.qq.com/q/synthetic")
        while not cancelled():
            time.sleep(0.01)
        seen.append("cancelled")
        raise InterruptedError

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "none.sqlite"))
        results = []
        async with app.run_test() as pilot:
            app.push_screen(QrLoginScreen(login=waiting_login), results.append)
            await pilot.pause(0.1)
            await pilot.press("escape")
            for _ in range(40):
                await pilot.pause(0.05)
                if seen:
                    break
        assert results == [False]
        assert seen == ["cancelled"]

    asyncio.run(scenario())


def test_splitter_drag_resizes_and_remembers(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "none.sqlite"))
        async with app.run_test(size=(120, 30)) as pilot:
            app.push_screen(SettingsScreen(SettingsModel(db_path=tmp_path / "none.sqlite")))
            await pilot.pause()
            categories = app.screen.query_one("#categories")
            before = categories.size.width
            await pilot.mouse_down(Splitter)
            await pilot.hover(Splitter, offset=(15, 0))
            await pilot.mouse_up(Splitter, offset=(15, 0))
            await pilot.pause()
            assert categories.size.width > before
            return int(categories.styles.width.value)

    width = asyncio.run(scenario())
    assert load_config()["layout"]["settings"] == width


def test_joined_contests_sync_and_confirm_collect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(
        "ojaudit.tui.account_service.detect_and_save_uid", lambda: "1234", raising=True
    )
    db = tmp_path / "s.sqlite"
    with Store(db) as store:
        store.import_contest(
            Contest("nowcoder", "1", "已采集的比赛", 1_700_000_000_000),
            submissions=[
                Submission("nowcoder", "1", "s1", "u1", 0, "cpp", "AC", 100, 1, "contest", "x")
            ],
        )

    class FakeSource:
        def list_joined(self, uid):
            assert uid == "1234"
            return [
                {"contest_id": "1", "name": "已采集的比赛", "start_time": None, "end_time": None},
                {
                    "contest_id": "2",
                    "name": "新参加的比赛",
                    "start_time": 1_800_000_000_000,
                    "end_time": None,
                },
            ]

    async def scenario():
        app = AuditApp(LocalContests(db))
        app.source_factory = FakeSource
        async with app.run_test() as pilot:
            app.push_screen(ContestListScreen(app.contests))
            await pilot.pause()
            await pilot.press("S")
            for _ in range(40):
                await pilot.pause(0.05)
                if len(app.screen.rows) == 2:
                    break
            names = [row.contest.name for row in app.screen.rows]
            assert names == ["新参加的比赛", "已采集的比赛"], "按开始时间倒序"
            assert "已同步 2 场比赛" in app.job_status
            await pilot.press("g", "enter")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmPopup)
            await pilot.press("n")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)

    asyncio.run(scenario())
    with Store(db) as store:
        assert store.list_contests()[0].start_time == 1_700_000_000_000, "不覆盖已有数据"


def test_appearance_applies_live_and_hot_reloads(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OJAUDIT_THEME_FILE", str(tmp_path / "none.json"))

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "none.sqlite"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.get_css_variables()["border-style"] == "round"
            app.apply_appearance({"theme": "nord", "border": "heavy", "transparent": True})
            await pilot.pause()
            assert app.theme == "nord"
            assert app.has_class("-ansi")
            variables = app.get_css_variables()
            assert variables["border-style"] == "heavy"
            assert variables["background"] == "ansi_default"
            assert app.syntax_theme == "ansi_dark"

            save_config({"appearance": {"theme": "dracula"}})
            app.poll_changes()
            await pilot.pause()
            assert app.theme == "dracula"
            assert not app.has_class("-ansi")

    asyncio.run(scenario())


def test_search_line_jumps_and_escape_restores(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    async def scenario():
        db = tmp_path / "s.sqlite"
        with Store(db) as store:
            for cid, name in (("1", "甲训练赛"), ("2", "乙训练赛"), ("3", "丙周赛")):
                store.put_contest_listing("nowcoder", cid, name, int(cid))
        app = AuditApp(LocalContests(db))
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.screen.query_one("#recent", ListView)
            names = [entry.contest.name for entry in app.screen.recent]
            await pilot.press("slash", *"丙")
            await pilot.pause()
            assert isinstance(app.screen, SearchLine)
            assert view.index == names.index("丙周赛")
            await pilot.press("escape")
            await pilot.pause()
            assert view.index == 0
            await pilot.press("slash", *"乙", "enter")
            await pilot.pause()
            assert view.index == names.index("乙训练赛")

    asyncio.run(scenario())


def test_settings_categories_are_merged():
    assert "过滤规则" in CATEGORIES
    assert "比赛筛选" not in CATEGORIES and "人员名单" not in CATEGORIES
