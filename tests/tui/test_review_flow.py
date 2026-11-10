"""
Module: Test / TUI review flow
Description: 证据页视图开关与持久化、快速标记与自动下一条、线索按人物对嫌疑度排序与表头点击排序、
    复核面板分组、拖动面板边框调整宽度、牛客官网链接。
Scope: Test
Notes: 只使用合成比赛、选手与代码。
"""

from __future__ import annotations

import asyncio

from textual.widgets import Static

from ojaudit.core.config import load_config
from ojaudit.core.schema import Contest, Participant, Problem, Submission
from ojaudit.core.store import Store
from ojaudit.tui.app import AuditApp
from ojaudit.tui.data import LocalContests
from ojaudit.tui.pending_screen import PendingScreen
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.review_screens import EvidenceScreen, FindingsScreen, nowcoder_links
from ojaudit.tui.settings_model import SettingsModel
from ojaudit.tui.settings_screen import SettingsScreen

SPACED = "n = int(input())\ncnt = 0\nfor i in range(n):\n    cnt += i\nprint(cnt)\n"
TIGHT = "n=int(input())\ncnt=0\nfor i in range(n):\n  cnt+=i\nprint(cnt)\n"


def _fixture(tmp_path):
    """a-b 在 A、B 两题都存疑（嫌疑 2），a-c 在 C 题实锤（嫌疑 3），b-c 在 A 题存疑。"""
    db = tmp_path / "flow.sqlite"
    cid = "143786"
    with Store(db) as store:
        people = [
            Participant("nowcoder", cid, uid, name)
            for uid, name in (("a", "甲"), ("b", "乙"), ("c", "丙"))
        ]
        problems = [Problem("nowcoder", cid, i, f"P{i}", f"题目{i}") for i in range(3)]
        subs = []
        for number, (uid, problem, code) in enumerate(
            (
                ("a", 0, SPACED),
                ("b", 0, TIGHT),
                ("c", 0, TIGHT),
                ("a", 1, SPACED),
                ("b", 1, TIGHT),
                ("a", 2, SPACED),
                ("c", 2, SPACED),
            )
        ):
            subs.append(
                Submission(
                    "nowcoder",
                    cid,
                    f"s{number}",
                    uid,
                    problem,
                    "python",
                    "AC",
                    100,
                    number,
                    "contest",
                    code,
                )
            )
        store.import_contest(Contest("nowcoder", cid, "合成赛"), people, problems, subs)
        findings = [
            ("a", "b", 0, "存疑"),
            ("a", "b", 1, "存疑"),
            ("a", "c", 2, "实锤"),
            ("b", "c", 0, "存疑"),
        ]
        store.save_analysis(
            "run",
            "nowcoder",
            cid,
            "x",
            "test",
            "2026-01-01",
            [
                {"uid_a": x, "uid_b": y, "problem_index": p, "language": "python", "level": level}
                for x, y, p, level in findings
            ],
        )
    local = LocalContests(db)
    return local, ReviewData(local, Contest("nowcoder", cid, "合成赛"))


def test_findings_grouped_by_pair_and_header_click_sorts(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local, data = _fixture(tmp_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test(size=(140, 30)) as pilot:
            app.push_screen(FindingsScreen(data, "首页"))
            await pilot.pause()
            pairs = [(r["uid_a"], r["uid_b"], r["problem_index"]) for r in app.screen.rows]
            assert pairs == [("a", "c", 2), ("a", "b", 0), ("a", "b", 1), ("b", "c", 0)]
            assert app.screen.cells(app.screen.rows[1])[1].plain == "A"
            header = app.screen.query_one(".thead")
            # 「题」列在等级（8 宽）之后，点击它按题号升序排序。
            await pilot.click(header, offset=(12, 0))
            await pilot.pause()
            assert app.screen.sort == (1, False)
            assert [r["problem_index"] for r in app.screen.rows] == [0, 0, 1, 2]

    asyncio.run(scenario())


def test_view_toggles_persist_and_change_comparison(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local, data = _fixture(tmp_path)
    finding = next(f for f in data.findings() if f["problem_index"] == 0 and f["uid_b"] == "b")

    async def scenario():
        app = AuditApp(local)
        async with app.run_test(size=(140, 36)) as pilot:
            app.push_screen(EvidenceScreen(data, "首页", finding))
            await pilot.pause()
            pane = app.screen.query_one("#pane-left")
            assert "不同 0 行" in str(pane.border_subtitle), "统一格式后只差空格的代码完全相同"
            await pilot.press("f")
            await pilot.pause()
            assert "不同 0 行" not in str(pane.border_subtitle), "关闭统一格式后能看到空格差异"
            assert load_config()["evidence"]["normalize"] is False
            await pilot.press("a")
            await pilot.pause()
            assert all(load_config()["evidence"].values())
            bar = app.screen.query_one("#view-bar", Static)
            start = next(s for s, _e, target in app.screen.toggle_spans if "rename" in target)
            await pilot.click(bar, offset=(start + 2, 0))
            await pilot.pause()
            assert load_config()["evidence"]["rename"] is False

    asyncio.run(scenario())


def test_quick_mark_resolves_other_findings_and_advances(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local, data = _fixture(tmp_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test(size=(140, 36)) as pilot:
            app.push_screen(FindingsScreen(data, "首页"))
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, EvidenceScreen)
            assert (screen.finding["uid_a"], screen.finding["uid_b"]) == ("a", "c")
            await pilot.press("m")
            await pilot.pause()
            app.screen.select("cheater")
            app.screen.save()
            await pilot.pause()
            statuses = {
                (f["uid_a"], f["uid_b"], f["problem_index"]): f["status"] for f in data.findings()
            }
            assert statuses[("a", "b", 0)] == "已核查"
            assert statuses[("a", "b", 1)] == "已核查"
            assert statuses[("b", "c", 0)] == "待复核"
            assert (screen.finding["uid_a"], screen.finding["uid_b"]) == ("b", "c"), (
                "自动跳到下一条"
            )
            assert data.person("a")["mark"] == "cheater"

    asyncio.run(scenario())


def test_review_panel_tabs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local, data = _fixture(tmp_path)
    data.review(data.findings()[0], "无需跟进", "")

    async def scenario():
        app = AuditApp(local)
        async with app.run_test(size=(140, 30)) as pilot:
            app.push_screen(PendingScreen())
            await pilot.pause()
            assert len(app.screen.rows) == 3
            await pilot.press("f")
            await pilot.pause()
            assert len(app.screen.rows) == 1
            await pilot.press("f")
            await pilot.pause()
            assert len(app.screen.rows) == 4
            assert "C" in {str(app.screen.cells(row)[2].plain) for row in app.screen.rows}, (
                "题号显示为字母"
            )

    asyncio.run(scenario())


def test_drag_panel_border_to_resize(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    async def scenario():
        app = AuditApp(LocalContests(tmp_path / "none.sqlite"))
        async with app.run_test(size=(120, 30)) as pilot:
            app.push_screen(SettingsScreen(SettingsModel(db_path=tmp_path / "none.sqlite")))
            await pilot.pause()
            categories = app.screen.query_one("#categories")
            before = categories.size.width
            border = categories.region.right - 1 - categories.region.x
            await pilot.mouse_down(categories, offset=(border, 3))
            await pilot.hover(categories, offset=(border + 10, 3))
            await pilot.mouse_up(categories, offset=(border + 10, 3))
            await pilot.pause()
            assert categories.size.width > before

    asyncio.run(scenario())


def test_nowcoder_links():
    contest = Contest("nowcoder", "143786", "合成赛")
    finding = {"problem_index": 2}
    links = dict(nowcoder_links(contest, finding, {"submission_id": "11"}, None))
    assert links["A 提交"].endswith("view-submission?submissionId=11")
    assert "B 提交" not in links
    assert links["题目"] == "https://ac.nowcoder.com/acm/contest/143786/C"
    assert nowcoder_links(Contest("other", "1", "x"), finding, None, None) == []
