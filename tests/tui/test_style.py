"""
Module: Test / TUI wallpaper style
Description: Synthetic pywal and Textual rendering smoke tests.
Scope: Test
Notes: Never reads real credentials or contest data.
"""

from __future__ import annotations

import asyncio
import json

from textual.widgets import ListView, Static

from ojaudit.core.store import Store
from ojaudit.tui.account_screen import AccountScreen
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.pending_screen import PendingScreen
from ojaudit.tui.ranking_screen import RankingScreen
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.review_screens import (
    CodeScreen,
    EvidenceScreen,
    FindingsScreen,
    PeopleScreen,
    PersonScreen,
    ProblemScreen,
    ProblemsScreen,
    SubmissionScreen,
)
from ojaudit.tui.rice_theme import load_wallpaper_theme, theme_from_dict
from ojaudit.tui.screens import ContestListScreen, ContestOverviewScreen, MissingContestScreen
from ojaudit.tui.settings_screen import SettingsScreen


def fake_colors(background: str = "#101820") -> dict:
    return {
        "special": {"background": background, "foreground": "#edf2f7"},
        "colors": {
            "color0": "#17202b",
            "color1": "#df7787",
            "color2": "#81c995",
            "color3": "#e9c67c",
            "color4": "#75acf0",
            "color5": "#be96ee",
            "color6": "#80d2dd",
            "color8": "#333d50",
        },
    }


def test_wallpaper_json_validation(tmp_path):
    path = tmp_path / "colors.json"
    path.write_text(json.dumps(fake_colors()), encoding="utf-8")
    theme, source = load_wallpaper_theme([path])
    assert source == str(path)
    assert theme is not None
    assert str(theme.background) == "#101820"
    assert theme_from_dict(fake_colors("not-a-hex")) is None
    assert theme_from_dict({"css": "Screen { display: none; }"}) is None
    path.write_text('{"colors": {"color4": "url(file:///private)"}}', encoding="utf-8")
    assert load_wallpaper_theme([path])[0] is None
    path.write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    assert load_wallpaper_theme([path])[0] is None


def test_auto_theme_and_change(tmp_path, monkeypatch):
    path = tmp_path / "wallpaper.json"
    path.write_text(json.dumps(fake_colors()), encoding="utf-8")
    monkeypatch.setenv("OJAUDIT_THEME_FILE", str(path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "missing.sqlite"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme_name == "auto"
            assert app.theme == "wallpaper"
            assert app.wallpaper_source == str(path)
            assert "" not in str(app.screen.query_one("#status").render())
            path.write_text(json.dumps(fake_colors("#182634")), encoding="utf-8")
            app.poll_wallpaper()
            assert app.theme == "wallpaper"
            assert app.wallpaper_signature is not None
            assert str(app.current_theme.background) == "#182634"

    asyncio.run(scenario())


def test_screenshots_with_synthetic_data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db = tmp_path / "synthetic.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "101", "虚构练习赛")
        with store.connection:
            for uid in ("person-a", "person-b"):
                store.execute(
                    "INSERT INTO participants(platform,contest_id,uid,name) VALUES(?,?,?,?)",
                    ("synthetic", "101", uid, uid),
                )
            store.execute(
                "INSERT INTO problems(platform,contest_id,problem_index,problem_id,title) "
                "VALUES(?,?,?,?,?)",
                ("synthetic", "101", 0, "P0", "合成测试题"),
            )
            for uid in ("person-a", "person-b"):
                store.execute(
                    "INSERT INTO submissions(platform,contest_id,submission_id,uid,"
                    "problem_index,language,verdict,score,submit_time,phase,code) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "synthetic",
                        "101",
                        "submission-" + uid,
                        uid,
                        0,
                        "python",
                        "AC",
                        100,
                        10,
                        "contest",
                        "print(1)",
                    ),
                )
            store.execute(
                "INSERT INTO analysis_runs(run_id,platform,contest_id,plugin_set,"
                "created_from,created_at) VALUES(?,?,?,?,?,?)",
                ("run-style", "synthetic", "101", "{}", "hash", "2026-01-01"),
            )
            store.execute(
                "INSERT INTO findings(run_id,uid_a,uid_b,problem_index,language,"
                "verdict_level,scores,reasons) VALUES(?,?,?,?,?,?,?,?)",
                ("run-style", "person-a", "person-b", 0, "python", "medium", "{}", "[]"),
            )

    async def scenario():
        app = AuditApp(LocalContests(db))
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            app.save_screenshot(filename="home.svg", path=str(tmp_path))
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen)
            app.save_screenshot(filename="contests.svg", path=str(tmp_path))
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ContestOverviewScreen)
            app.save_screenshot(filename="overview.svg", path=str(tmp_path))
            contest = app.screen.contest
            data = ReviewData(app.contests, contest)
            app.push_screen(EvidenceScreen(data, "首页 › 比赛列表", data.findings()[0]))
            await pilot.pause()
            app.save_screenshot(filename="evidence.svg", path=str(tmp_path))
            app.pop_screen()
            await pilot.pause()
            more_pages = (
                ("findings.svg", FindingsScreen(data, "首页 › 比赛列表")),
                ("people.svg", PeopleScreen(data, "首页 › 比赛列表")),
                ("person.svg", PersonScreen(data, "首页 › 比赛列表", "person-a")),
                (
                    "submissions.svg",
                    SubmissionScreen(data, "首页 › 比赛列表", "person-a", 0),
                ),
                ("problems.svg", ProblemsScreen(data, "首页 › 比赛列表")),
                (
                    "problem.svg",
                    ProblemScreen(data, "首页 › 比赛列表", 0, "合成测试题"),
                ),
                (
                    "code.svg",
                    CodeScreen(
                        data,
                        "首页 › 比赛列表",
                        data.submissions("person-a", 0),
                    ),
                ),
                ("account.svg", AccountScreen()),
                ("pending.svg", PendingScreen()),
                ("missing.svg", MissingContestScreen("404")),
            )
            for filename, screen in more_pages:
                app.push_screen(screen)
                await pilot.pause()
                app.save_screenshot(filename=filename, path=str(tmp_path))
                app.pop_screen()
                await pilot.pause()
            app.push_screen(RankingScreen(data))
            await pilot.pause()
            app.save_screenshot(filename="ranking.svg", path=str(tmp_path))
            app.pop_screen()
            await pilot.pause()
            app.push_screen(SettingsScreen())
            await pilot.pause()
            app.screen.category_index = 6
            app.screen.reload()
            await pilot.pause()
            app.save_screenshot(filename="settings.svg", path=str(tmp_path))
            assert app.screen.query_one(ListView)
            assert app.screen.query_one("#status", Static)

    asyncio.run(scenario())
    for name in (
        "home.svg",
        "contests.svg",
        "overview.svg",
        "settings.svg",
        "evidence.svg",
        "ranking.svg",
        "findings.svg",
        "people.svg",
        "person.svg",
        "submissions.svg",
        "problems.svg",
        "problem.svg",
        "code.svg",
        "account.svg",
        "pending.svg",
        "missing.svg",
    ):
        data = (tmp_path / name).read_text(encoding="utf-8")
        assert "<svg" in data
