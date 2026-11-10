"""
Module: Test / TUI workflow
Description: 合成 Source 走通后台采集、检测、总览与待复核，以及取消任务。
Scope: Test
Notes: 只使用合成数据，不访问网络。
"""

import asyncio
import threading

from ojaudit.core.schema import Contest, Participant, Problem, Submission
from ojaudit.core.store import Store
from ojaudit.plugins.sources.nowcoder import NowcoderBundle
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.pending_screen import PendingScreen
from ojaudit.tui.screens import ContestOverviewScreen, MissingContestScreen
from ojaudit.tui.workflow import pending_entries


def bundle():
    code = "int main(){int value=1;return value+1;}"
    return NowcoderBundle(
        contest=Contest("nowcoder", "42", "虚构比赛"),
        problems=(Problem("nowcoder", "42", 0, "P0", "虚构题目"),),
        participants=(
            Participant("nowcoder", "42", "fake-a", "选手甲"),
            Participant("nowcoder", "42", "fake-b", "选手乙"),
        ),
        submissions=(
            Submission(
                "nowcoder", "42", "s1", "fake-a", 0, "cpp", "Accepted", 100, 1000, "contest", code
            ),
            Submission(
                "nowcoder", "42", "s2", "fake-b", 0, "cpp", "Accepted", 100, 2000, "contest", code
            ),
        ),
    )


class FakeSource:
    def fetch_contest(self, session, contest_id):
        assert contest_id == "42"
        return bundle()


def test_collect_analyze_pending_and_overview(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local = LocalContests(tmp_path / "fake.sqlite")

    async def scenario():
        app = AuditApp(local)
        app.source_factory = FakeSource
        async with app.run_test() as pilot:
            assert not pending_entries(local)
            app.start_workflow("42", "collect_analyze")
            for _ in range(100):
                await pilot.pause(0.05)
                if not app.job_running:
                    break
            assert not app.job_running
            assert "任务完成" in app.job_status
            contest = local.list_contests()[0].contest
            assert local.stats(contest).submissions == 2
            assert local.stats(contest).findings >= 1
            assert pending_entries(local)
            app.push_screen(ContestOverviewScreen(contest, local))
            await pilot.pause()
            assert "提交 2" in str(app.screen.query_one("#summary").render())
            app.push_screen(PendingScreen())
            await pilot.pause()
            assert app.screen.entries
            app.screen.open_index(0)
            await pilot.pause()
            assert "证据" in app.screen.PATH

    asyncio.run(scenario())


def test_cancel_before_database_write(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local = LocalContests(tmp_path / "fake.sqlite")
    entered = threading.Event()
    released = threading.Event()

    class SlowSource:
        def fetch_contest(self, session, contest_id):
            entered.set()
            assert released.wait(10)
            return bundle()

    async def scenario():
        app = AuditApp(local)
        app.source_factory = SlowSource
        async with app.run_test() as pilot:
            app.start_workflow("42", "collect_analyze")
            for _ in range(100):
                await pilot.pause(0.05)
                if entered.is_set():
                    break
            assert entered.is_set()
            app.cancel_workflow()
            released.set()
            for _ in range(100):
                await pilot.pause(0.05)
                if not app.job_running:
                    break
            assert not app.job_running
            assert "取消" in app.job_status
            assert not local.db_path.is_file()

    asyncio.run(scenario())


def test_missing_contest_keeps_actionable_screen(tmp_path):
    with Store(tmp_path / "fake.sqlite"):
        pass
    screen = MissingContestScreen("42")
    assert screen.contest_id == "42"
    assert screen.OPTIONS[0] == "采集并检测"
