"""
Module: Test / Nerd Font icons
Description: 图标开关两态下所有主要页面均可渲染，关闭时不输出私有区字符。
Scope: Test
Notes: 只使用合成数据。
"""

import asyncio

import pytest
from textual.widgets import ListView, Static

from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.icons import GLYPHS, breadcrumb, glyph, label
from ojaudit.tui.ranking_screen import RankingScreen
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.review_screens import (
    ChoiceDialog,
    CodeScreen,
    EvidenceScreen,
    FindingsScreen,
    PeopleScreen,
    ProblemsScreen,
)
from ojaudit.tui.screens import ContestListScreen, ContestOverviewScreen, EntryDialog, HomeScreen
from ojaudit.tui.settings_model import SettingsModel
from ojaudit.tui.settings_screen import ConfirmLeave, EditValue, SettingsScreen


def _private(text: str) -> bool:
    return any(0xE000 <= ord(char) <= 0xF8FF for char in text)


def test_central_icons_and_plain_fallback():
    assert GLYPHS
    assert all(_private(value) for value in GLYPHS.values())
    for key in GLYPHS:
        assert glyph(key, False) == ""
        assert not _private(label(key, "合成文字", False))
    assert not _private(breadcrumb("首页 › 比赛 › 代码", False))
    assert _private(breadcrumb("首页 › 比赛 › 代码", True))


@pytest.mark.parametrize("enabled", [False, True])
def test_all_major_screens_render_with_icon_mode(tmp_path, enabled):
    db = tmp_path / "fake.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "demo", "虚构训练赛")
        with store.connection:
            store.execute(
                "INSERT INTO participants(platform,contest_id,uid,name) VALUES(?,?,?,?)",
                ("synthetic", "demo", "fake-user", "虚构选手"),
            )
            store.execute(
                "INSERT INTO problems(platform,contest_id,problem_index,problem_id,title) "
                "VALUES(?,?,?,?,?)",
                ("synthetic", "demo", 0, "P0", "虚构题目"),
            )
    local = LocalContests(db)
    contest = local.list_contests()[0].contest
    data = ReviewData(local, contest)

    async def scenario():
        app = AuditApp(local)
        app.nerd_font = enabled
        async with app.run_test() as pilot:
            screens = (
                HomeScreen(),
                ContestListScreen(local),
                ContestOverviewScreen(contest, local),
                FindingsScreen(data, "首页 › 线索"),
                PeopleScreen(data, "首页 › 选手"),
                ProblemsScreen(data, "首页 › 题目"),
                RankingScreen(data),
                SettingsScreen(SettingsModel(tmp_path / "settings.toml", [], db_path=db)),
                EntryDialog(),
                EntryDialog(login=True),
                ChoiceDialog("虚构标记", (("正常", "normal"),)),
                ConfirmLeave(),
                EditValue(
                    SettingsModel(tmp_path / "settings.toml", [], db_path=db).options[0],
                    "fake",
                ),
                CodeScreen(
                    data,
                    "首页 › 代码",
                    [
                        {
                            "uid": "fake-user",
                            "submission_id": "fake-s1",
                            "problem_index": 0,
                            "verdict": "AC",
                            "language": "python",
                            "code": "print(1)",
                        }
                    ],
                ),
                EvidenceScreen(
                    data,
                    "首页 › 线索",
                    {
                        "uid_a": "fake-user",
                        "uid_b": "fake-user",
                        "problem_index": 0,
                        "language": "python",
                        "verdict_level": "low",
                        "status": "待复核",
                        "is_stale": False,
                        "reasons": ["虚构理由"],
                        "scores": {"fake": 0.5},
                    },
                ),
            )
            for screen in screens:
                app.push_screen(screen)
                await pilot.pause()
                svg = app.export_screenshot()
                assert _private(svg) is enabled
                app.pop_screen()
                await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            assert _private(app.export_screenshot()) is enabled
            assert app.screen.query_one(ListView).children
            assert "帮助" in str(app.screen.query_one("#status", Static).render())

    asyncio.run(scenario())
