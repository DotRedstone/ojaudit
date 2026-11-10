"""
Module: Test / TUI mouse and jobs
Description: 顶栏点击不再弹空首页、点击任务状态取消、采集进度与取消、Ctrl+C 退出、同步清理旧登记、
    名称实体解码，以及提示栏、弹窗操作、设置项的纯鼠标操作。
Scope: Test
Notes: 只使用合成数据与假数据源，不访问网络。
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest
from textual.widgets import ListView

from ojaudit.core.schema import Contest, Participant, Submission
from ojaudit.core.store import Store
from ojaudit.plugins.sources.nowcoder import NowcoderSource
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.popup import ConfirmPopup, InputPopup
from ojaudit.tui.screens import ContestListScreen, HomeScreen
from ojaudit.tui.settings_model import CATEGORIES, SettingsModel
from ojaudit.tui.settings_screen import SettingsScreen


def test_clicking_status_bar_on_home_does_not_pop_it(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "none.sqlite"))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#status", offset=(70, 0))
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("q")
            await pilot.pause()
        assert app.return_code in (0, None)

    asyncio.run(scenario())


class SlowSource:
    """报告进度、支持取消的假数据源。"""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def fetch_contest(self, session, contest_id, *, progress=None, cancelled=None):
        progress("下载源码", 0, 100)
        self.started.set()
        for done in range(1, 101):
            if cancelled():
                self.stopped.set()
                raise InterruptedError("采集已取消")
            progress("下载源码", done, 100)
            threading.Event().wait(0.01)
        raise AssertionError("应当在完成前被取消")


def test_progress_is_shown_and_clicking_status_cancels(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    source = SlowSource()

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "db.sqlite"))
        app.source_factory = lambda: source
        async with app.run_test(size=(140, 30)) as pilot:
            app.start_workflow("42", "collect")
            for _ in range(60):
                await pilot.pause(0.05)
                if app.job_progress and app.job_progress[1] > 3:
                    break
            bar = str(app.screen.query_one("#status").render())
            assert "下载源码" in bar and "/100" in bar
            await pilot.click("#status", offset=(135, 0))
            await pilot.pause()
            assert isinstance(app.screen, ConfirmPopup)
            await pilot.press("y")
            for _ in range(60):
                await pilot.pause(0.05)
                if not app.job_running:
                    break
            assert "取消" in app.job_status
            assert app.job_progress is None
        assert source.stopped.is_set()

    asyncio.run(scenario())


def test_ctrl_c_cancels_background_job_and_exits(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    source = SlowSource()

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "db.sqlite"))
        app.source_factory = lambda: source
        async with app.run_test() as pilot:
            app.start_workflow("42", "collect")
            for _ in range(60):
                await pilot.pause(0.05)
                if source.started.is_set():
                    break
            await pilot.press("ctrl+c")
            await pilot.pause()

    asyncio.run(scenario())
    assert source.stopped.wait(2)


def test_source_cancellation_stops_remaining_downloads():
    requests = []

    class Response:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body.encode()

    stop = threading.Event()

    def opener(request, timeout):
        url = request.full_url
        requests.append(url)
        if "contest-info" in url:
            return Response(json.dumps({"data": {"name": "&quot;合成&quot;杯"}}))
        if "submit-list" in url:
            subs = [
                {"submissionId": str(i), "uid": "u", "problemId": "p", "submitTime": i}
                for i in range(200)
            ]
            return Response(
                json.dumps(
                    {
                        "data": {
                            "problemData": [{"problemId": "p", "index": 0, "title": "A&amp;B"}],
                            "submitDataList": [{"signUpUsers": [], "submissions": subs}],
                        }
                    }
                )
            )
        if len(requests) > 10:
            stop.set()
        return Response("<pre>int main(){}</pre>")

    source = NowcoderSource({"cookie": "t=x", "threads": 4}, opener=opener)
    seen = []
    with pytest.raises(InterruptedError):
        source.fetch_contest(
            None, "1", progress=lambda *args: seen.append(args), cancelled=stop.is_set
        )
    assert len(requests) < 60, "取消后不再继续下载剩余源码"
    assert seen[0][0] == "读取比赛信息"
    assert any(stage == "下载源码" and total == 200 for stage, _, total in seen)


def test_listings_are_pruned_and_names_decoded(tmp_path):
    with Store(tmp_path / "s.sqlite") as store:
        store.import_contest(
            Contest("nowcoder", "1", "已采集"),
            [Participant("nowcoder", "1", "u", "甲")],
            submissions=[
                Submission("nowcoder", "1", "s", "u", 0, "cpp", "AC", 100, 1, "contest", "x")
            ],
        )
        store.put_contest_listing("nowcoder", "2", "&quot;旧&quot;")
        store.put_contest_listing("nowcoder", "2", '"旧"')
        store.put_contest_listing("nowcoder", "3", "已不在列表")
        assert store.prune_listings("nowcoder", {"2"}) == 1
        names = {c.contest_id: c.name for c in store.list_contests()}
        assert names == {"1": "已采集", "2": '"旧"'}

    class Response:
        def read(self):
            row = {"contestId": 9, "contestName": "&ldquo;范式杯&rdquo;", "startTime": 1}
            return json.dumps({"data": {"dataList": [row], "pageInfo": {"totalCount": 1}}}).encode()

    source = NowcoderSource({"cookie": "t=x"}, opener=lambda request, timeout: Response())
    assert source.list_joined("123")[0]["name"] == "“范式杯”"


def test_key_bar_and_popup_actions_work_with_mouse(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    db = tmp_path / "s.sqlite"
    with Store(db) as store:
        store.put_contest_listing("nowcoder", "7", "未采集的比赛")

    async def scenario():
        app = AuditApp(LocalContests(db))
        async with app.run_test(size=(120, 30)) as pilot:
            app.push_screen(ContestListScreen(app.contests))
            await pilot.pause()
            bar = app.screen.query_one("#status")
            start, _end, key = next(span for span in bar.spans if span[2] == "c")
            await pilot.click("#status", offset=(start + 1, 0))
            await pilot.pause()
            assert isinstance(app.screen, InputPopup), key
            await pilot.click(offset=(1, 1))
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen), "点击弹窗外部即取消"

            await pilot.double_click("ContestListScreen ListItem", offset=(3, 0))
            await pilot.pause()
            assert isinstance(app.screen, ConfirmPopup)
            row = app.screen.query_one(".popup-hints")
            total = row.spans[-1][1]
            start, _end, _action = next(span for span in row.spans if span[2] == "answer(False)")
            await pilot.click(row, offset=(row.size.width - total + start + 1, 0))
            await pilot.pause()
            assert isinstance(app.screen, ContestListScreen), "点击「否」"

    asyncio.run(scenario())


def test_settings_fully_operable_with_mouse(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    model = SettingsModel(tmp_path / "config.toml", [], db_path=tmp_path / "none.sqlite")

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "none.sqlite"))
        async with app.run_test(size=(120, 30)) as pilot:
            app.push_screen(SettingsScreen(model))
            await pilot.pause()
            categories = app.screen.query_one("#categories", ListView)
            index = CATEGORIES.index("外观")
            await pilot.click(categories.children[index])
            await pilot.pause()
            assert app.screen.category == "外观"
            values = app.screen.query_one("#settings-values", ListView)
            keys = [option.key for option in app.screen.rows]
            row = values.children[keys.index("appearance.line_numbers")]
            await pilot.double_click(row)
            await pilot.pause()
            assert app.screen.focus_values
            assert model.values["appearance.line_numbers"] is False
            assert app.line_numbers is False

    asyncio.run(scenario())
