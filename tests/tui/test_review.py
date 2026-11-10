"""
Module: Test / TUI review
Description: 用合成数据与 Pilot 验证证据复核、同步标记及提交导航。
Scope: Test
Notes: 不包含真实比赛、UID 或选手代码。
"""

import asyncio
import json

from textual.widgets import Button, Input, Select

from ojaudit.core.filters import ContestFilter
from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.review_screens import (
    ChoiceDialog,
    CodeScreen,
    EvidenceScreen,
    FindingsScreen,
    PeopleScreen,
    PersonScreen,
)
from ojaudit.tui.screens import ContestListScreen, ContestOverviewScreen


def fixture(tmp_path):
    path = tmp_path / "synthetic.db"
    with Store(path) as store:
        store.put_contest("example", "contest-a", "虚构训练赛")
        with store.connection:
            for uid in ("fake-a", "fake-b", "fake-c"):
                store.execute(
                    "INSERT INTO participants(platform,contest_id,uid,name) VALUES(?,?,?,?)",
                    ("example", "contest-a", uid, "选手" + uid[-1]),
                )
            store.execute(
                "INSERT INTO problems(platform,contest_id,problem_index,problem_id,title) "
                "VALUES(?,?,?,?,?)",
                ("example", "contest-a", 0, "P0", "合成题目"),
            )
            for submission_id, uid, verdict, score, time, code in (
                ("s1", "fake-a", "WA", 0, 10, "print('a')\n"),
                ("s2", "fake-a", "AC", 100, 20, "print('b')\n"),
                ("s3", "fake-b", "AC", 100, 30, "print('c')\n"),
                ("s4", "fake-c", "CE", 0, 40, "print('d')\n"),
            ):
                store.execute(
                    "INSERT INTO submissions(platform,contest_id,submission_id,uid,"
                    "problem_index,language,verdict,score,submit_time,phase,code) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "example",
                        "contest-a",
                        submission_id,
                        uid,
                        0,
                        "python",
                        verdict,
                        score,
                        time,
                        "contest",
                        code,
                    ),
                )
            store.execute(
                "INSERT INTO analysis_runs(run_id,platform,contest_id,plugin_set,"
                "created_from,created_at) VALUES(?,?,?,?,?,?)",
                ("run-synthetic", "example", "contest-a", "{}", "fake-hash", "2026-01-01"),
            )
            for u1, u2 in (("fake-a", "fake-b"), ("fake-a", "fake-c")):
                store.execute(
                    "INSERT INTO findings(run_id,uid_a,uid_b,problem_index,language,"
                    "verdict_level,scores,reasons) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        "run-synthetic",
                        u1,
                        u2,
                        0,
                        "python",
                        "medium",
                        json.dumps({"demo_detector": 0.8}),
                        json.dumps(["合成检测理由", "时间线：虚构"]),
                    ),
                )
        store.put_hidden_person("example", "fake-c", "管理")
    local = LocalContests(path, ContestFilter())
    contest = local.list_contests()[0].contest
    return local, ReviewData(local, contest)


async def navigate_overview(app, pilot):
    await pilot.press("enter")
    await pilot.pause()
    assert isinstance(app.screen, ContestListScreen)
    await pilot.press("enter")
    await pilot.pause()
    assert isinstance(app.screen, ContestOverviewScreen)


def test_evidence_diff_review_auto_advance(tmp_path):
    local, data = fixture(tmp_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test() as pilot:
            await navigate_overview(app, pilot)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, FindingsScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            first = app.screen.finding
            assert first["uid_b"] == "fake-b"
            await pilot.press("tab")
            assert app.screen.diff_mode
            await pilot.press("r")
            await pilot.pause()
            assert isinstance(app.screen, ChoiceDialog)
            app.screen.query_one("#choice", Select).value = "已核查"
            app.screen.query_one("#note", Input).value = "已比对"
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            assert app.screen.finding["uid_b"] == "fake-c"
            reviews = data.findings()
            assert reviews[0]["status"] == "已核查"
            assert reviews[0]["note"] == "已比对"
            assert reviews[1]["status"] == "待复核"

    asyncio.run(scenario())


def test_mark_synchronizes_across_screens(tmp_path):
    local, data = fixture(tmp_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test() as pilot:
            await navigate_overview(app, pilot)
            await pilot.press("enter", "enter")
            await pilot.pause()
            assert isinstance(app.screen, EvidenceScreen)
            await pilot.press("m")
            await pilot.pause()
            assert isinstance(app.screen, ChoiceDialog)
            app.screen.query_one("#choice", Select).value = "suspect"
            app.screen.query_one("#note", Input).value = "人工复核"
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            assert data.person("fake-a")["mark"] == "suspect"
            await pilot.press("escape", "escape")
            await pilot.pause()
            assert isinstance(app.screen, ContestOverviewScreen)
            app.screen.query_one("ListView").index = 1
            await pilot.press("l")
            await pilot.pause()
            assert isinstance(app.screen, PeopleScreen)
            assert "存疑" in app.screen.label_for(data.person("fake-a"))
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PersonScreen)
            await pilot.press("m")
            await pilot.pause()
            assert isinstance(app.screen, ChoiceDialog)
            assert app.screen.query_one("#choice", Select).value == "suspect"
            app.screen.query_one("#cancel", Button).press()
            await pilot.pause()
            assert isinstance(app.screen, PersonScreen)

    asyncio.run(scenario())


def test_history_and_people_problem_navigation(tmp_path):
    local, _data = fixture(tmp_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test() as pilot:
            await navigate_overview(app, pilot)
            app.screen.query_one("ListView").index = 1
            await pilot.press("l")
            await pilot.pause()
            assert isinstance(app.screen, PeopleScreen)
            await pilot.press("enter", "enter", "enter")
            await pilot.pause()
            assert isinstance(app.screen, CodeScreen)
            assert app.screen.current["submission_id"] == "s1"
            await pilot.press("n")
            assert app.screen.current["submission_id"] == "s2"
            await pilot.press("left_square_bracket")
            assert app.screen.current["submission_id"] == "s1"
            await pilot.press("right_square_bracket")
            assert app.screen.current["submission_id"] == "s2"
            await pilot.press("p")
            assert app.screen.current["submission_id"] == "s1"
            await pilot.press("escape", "escape", "escape", "escape")
            await pilot.pause()
            assert isinstance(app.screen, ContestOverviewScreen)
            app.screen.query_one("ListView").index = 2
            await pilot.press("l", "enter", "enter")
            await pilot.pause()
            assert isinstance(app.screen, CodeScreen)

    asyncio.run(scenario())


def test_stale_findings_and_manager(tmp_path):
    local, data = fixture(tmp_path)
    with Store(local.db_path) as store:
        with store.connection:
            store.execute(
                "INSERT INTO analysis_runs(run_id,platform,contest_id,plugin_set,"
                "created_from,created_at) VALUES(?,?,?,?,?,?)",
                ("old-run", "example", "contest-a", "{}", "old", "2025-01-01"),
            )
        store.put_finding_review(
            "old-run",
            "fake-b",
            "fake-c",
            0,
            "python",
            "已核查",
            updated_at="2025-01-01",
        )
    stale = [item for item in data.findings() if item["is_stale"]]
    assert len(stale) == 1
    assert stale[0]["status"] == "已核查"
    assert data.person("fake-c")["hidden"]
    assert data.representatives(0, "name")
    assert data.representatives(0, "findings")
    assert data.representatives(0, "time")
