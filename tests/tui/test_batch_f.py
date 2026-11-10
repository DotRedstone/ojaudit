"""
Module: Test / batch F account and secondary features
Description: 使用合成票据与本地 SQLite 验证账户、线索筛选和比赛列表。
Scope: Test
Notes: 不使用真实 Cookie/UID，不向牛客发起网络请求。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from types import SimpleNamespace

import pytest
from textual.widgets import Label, ListView, Static

from ojaudit.cli_operations import cookie_file
from ojaudit.core.store import Store
from ojaudit.tui.account_screen import AccountScreen, UidDialog
from ojaudit.tui.account_service import (
    _wechat_url,
    current_uid,
    logged_in_locally,
    login_with_qr,
    logout,
    qr_terminal_text,
    set_uid,
)
from ojaudit.tui.app import AuditApp
from ojaudit.tui.contest_list_data import contest_list_description
from ojaudit.tui.data import LocalContests
from ojaudit.tui.review_screens import FindingsScreen
from ojaudit.tui.screens import ContestListScreen


def test_uid_logout_and_local_cookie_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    set_uid("  123456  ")
    assert current_uid() == "123456"
    with pytest.raises(ValueError):
        set_uid("not-a-uid")
    assert not logged_in_locally()
    file = cookie_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("t=synthetic-only", encoding="utf-8")
    assert logged_in_locally()
    logout()
    assert not file.exists()
    assert current_uid() == "123456"


def test_qr_login_offline_does_not_expose_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    url = "https://weixin.qq.com/q/synthetic"
    ticket = base64.b64encode(("prefix:" + url).encode()).decode()
    assert _wechat_url(ticket) == url
    with pytest.raises(ValueError):
        _wechat_url(base64.b64encode(b"https://evil.example/q/nope").decode())
    assert "██" in qr_terminal_text(url)

    class FakeResponse:
        def __init__(self, value):
            self.value = value

        def read(self):
            return json.dumps(self.value).encode("utf-8")

    class FakeJar:
        def __iter__(self):
            return iter(
                [SimpleNamespace(name="t", value="synthetic-secret", domain=".nowcoder.com")]
            )

    class FakeClient:
        def open(self, request, timeout):
            assert timeout == 20
            if "wechat_qr_code" in request.full_url:
                return FakeResponse({"data": {"ticket": ticket, "expireSecond": 120}})
            assert "wechat_mp_status" in request.full_url
            return FakeResponse({"code": 0})

    messages = []
    login_with_qr(
        messages.append,
        opener=FakeClient(),
        cookie_jar=FakeJar(),
        pause=lambda _seconds: None,
        clock=lambda: 0,
    )
    assert logged_in_locally()
    assert cookie_file().read_text(encoding="utf-8") == "t=synthetic-secret"
    assert os.stat(cookie_file()).st_mode & 0o777 == 0o600
    assert "synthetic-secret" not in "\n".join(messages)
    assert ticket not in "\n".join(messages)


def _local_contest(tmp_path):
    db = tmp_path / "sample.sqlite"
    with Store(db) as store:
        store.put_contest("synthetic", "42", "虚构比赛")
        with store.connection:
            store.execute(
                "UPDATE contests SET start_time=? WHERE platform=? AND contest_id=?",
                (1760000000, "synthetic", "42"),
            )
            store.execute(
                "INSERT INTO participants(platform,contest_id,uid,name) VALUES(?,?,?,?)",
                ("synthetic", "42", "student-1", "甲"),
            )
            store.execute(
                "INSERT INTO submissions(platform,contest_id,submission_id,uid,"
                "problem_index,language,verdict,score,submit_time,phase,code) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "synthetic",
                    "42",
                    "s-1",
                    "student-1",
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
                ("run-f", "synthetic", "42", "synthetic", "test", "2026-01-01"),
            )
            store.execute(
                "INSERT INTO findings(run_id,uid_a,uid_b,problem_index,language,"
                "verdict_level,scores,reasons) VALUES(?,?,?,?,?,?,?,?)",
                ("run-f", "student-1", "student-2", 0, "python", "high", "{}", "[]"),
            )
    return LocalContests(db)


def test_contest_list_description_and_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local = _local_contest(tmp_path)
    contest = local.list_contests()[0].contest
    result = contest_list_description(local, contest)
    assert "提交 1" in result
    assert "已分析" in result
    assert "线索 1/0/0" in result
    assert "复核 0/1" in result

    async def scenario():
        app = AuditApp(local)
        async with app.run_test() as pilot:
            app.push_screen(ContestListScreen(local))
            await pilot.pause()
            view = app.screen.query_one("#contests", ListView)
            assert "线索 1/0/0" in str(view.children[0].query_one(Label).render())
            app.push_screen(AccountScreen())
            await pilot.pause()
            assert "本机未保存 Cookie" in str(
                app.screen.query_one("#account-state", Static).render()
            )
            app.screen.open_index(1)
            await pilot.pause()
            assert isinstance(app.screen, UidDialog)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, AccountScreen)

    asyncio.run(scenario())


def test_findings_filter_all_high_pending_reviewed():
    data = SimpleNamespace(
        findings=lambda: [
            {"is_stale": False, "verdict_level": "high", "status": "待复核"},
            {"is_stale": False, "verdict_level": "low", "status": "已核查"},
            {"is_stale": True, "verdict_level": "high", "status": "已核查"},
        ]
    )
    screen = FindingsScreen(data, "首页 › 虚构比赛")
    assert len(screen.items()) == 3
    screen.filter_index = 1
    assert len(screen.items()) == 1
    screen.filter_index = 2
    assert len(screen.items()) == 1
    screen.filter_index = 3
    assert len(screen.items()) == 1
