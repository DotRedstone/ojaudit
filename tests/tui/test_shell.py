"""
Module: Test / TUI shell
Description: 使用 Textual Pilot 验证只读比赛导航和屏幕栈。
Scope: Test
Notes: 全部比赛和人员数据均为合成内容。
"""

import asyncio

from ojaudit.core.filters import ContestFilter, ContestRule
from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.screens import ContestListScreen, ContestOverviewScreen, HomeScreen


def _fixtures(tmp_path):
    db = tmp_path / "demo.sqlite3"
    with Store(db) as store:
        store.put_contest("synthetic", "101", "校内练习甲")
        store.put_contest("synthetic", "102", "公开示例乙")
        with store.connection:
            store.execute(
                "INSERT INTO participants(platform, contest_id, uid, name) VALUES (?, ?, ?, ?)",
                ("synthetic", "101", "test-user", "虚构选手"),
            )
            store.execute(
                "INSERT INTO problems(platform, contest_id, problem_index, problem_id, title) "
                "VALUES (?, ?, ?, ?, ?)",
                ("synthetic", "101", 0, "P0", "虚构题目"),
            )
    return LocalContests(
        db,
        ContestFilter(rules=(ContestRule("校内"),), mode="whitelist"),
    )


def test_readonly_filter_and_stats(tmp_path):
    source = _fixtures(tmp_path)
    assert [entry.contest.contest_id for entry in source.list_contests()] == ["101"]
    assert len(source.list_contests(show_all=True)) == 2
    assert source.stats(source.list_contests()[0].contest).participants == 1
    assert source.stats(source.list_contests()[0].contest).problems == 1


def test_navigation_and_page_edges(tmp_path):
    source = _fixtures(tmp_path)

    async def scenario():
        app = AuditApp(source)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            assert str(app.screen.query_one("#frame-top").render()).count("╭") == 1
            await pilot.press("1")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            assert len(app.screen.entries) == 1
            assert "首页" in str(app.screen.query_one("#frame-top").render())
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ContestOverviewScreen)
            pages = str(app.screen.query_one("#frame-top").render()).splitlines()
            assert [line.count("│") for line in pages] == [0, 1, 2], "上层页面依次错开叠放"
            assert "比赛列表" in pages[1] and "校内练习甲" in pages[2]
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            await pilot.press("a")
            await pilot.pause()
            assert len(app.screen.entries) == 2
            await pilot.press("h")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("question_mark")
            await pilot.press("q")

    asyncio.run(scenario())


def test_empty_store(tmp_path):
    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "missing.db", ContestFilter()))
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            assert not app.screen.entries
            await pilot.press("l")
            assert isinstance(app.screen, ContestListScreen)
            await pilot.press("q")

    asyncio.run(scenario())
