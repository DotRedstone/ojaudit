"""
Module: Test / TUI review flow
Description: 证据页视图开关与持久化、快速复核、撤销与自动下一条、线索按人物对嫌疑度排序与表头点击排序、
    复核面板分组、拖动面板边框调整宽度、牛客官网链接。
Scope: Test
Notes: 只使用合成比赛、选手与代码。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import ListView, Static

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
            await pilot.press("enter")
            await pilot.pause()
            app.screen.select("cheater:a")
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
            assert data.person("c")["mark"] == "", "只认定甲作弊时不牵连丙"

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


def test_ranking_quick_manager_and_inactive_policy(tmp_path, monkeypatch):
    from ojaudit.tui.ranking_screen import POLICIES, RankingScreen

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local, data = _fixture(tmp_path)
    with Store(local.db_path) as store:
        store.put_participants([Participant("nowcoder", "143786", "idle", "只报名")])

    async def scenario():
        app = AuditApp(local)
        async with app.run_test(size=(140, 34)) as pilot:
            app.push_screen(RankingScreen(data))
            await pilot.pause()
            screen = app.screen
            uids = [row["uid"] for row in screen.preview_rows]
            assert "idle" in uids
            inactive = [name for name, _, _ in POLICIES].index("未提交者")
            screen.query_one("#ranking-options", ListView).index = inactive
            await pilot.press("l")
            await pilot.pause()
            assert screen.policy().inactive == "drop"
            assert "idle" not in [row["uid"] for row in screen.preview_rows]

            preview = screen.query_one("#ranking-preview", ListView)
            preview.focus()
            preview.index = [row["uid"] for row in screen.preview_rows].index("b")
            await pilot.press("a")
            await pilot.pause()
            assert "b" not in [row["uid"] for row in screen.preview_rows], "管理者默认剔除"
            assert data.person("b")["hidden"]
            managers = [name for name, _, _ in POLICIES].index("管理者")
            screen.choice_indices[managers] = 1
            screen.refresh_ranking()
            preview.index = [row["uid"] for row in screen.preview_rows].index("b")
            await pilot.press("a")
            await pilot.pause()
            assert not data.person("b")["hidden"], "再按一次取消"

    asyncio.run(scenario())


def test_people_page_quick_manager(tmp_path, monkeypatch):
    from ojaudit.tui.review_screens import PeopleScreen

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local, data = _fixture(tmp_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test(size=(140, 30)) as pilot:
            app.push_screen(PeopleScreen(data, "首页"))
            await pilot.pause()
            view = app.screen.query_one("#items", ListView)
            view.index = [row["uid"] for row in app.screen.rows].index("c")
            await pilot.press("a")
            await pilot.pause()
            assert data.person("c")["hidden"]

    asyncio.run(scenario())


def test_undo_review_restores_quick_resolved_findings(tmp_path):
    _local, data = _fixture(tmp_path)

    def finding(a, b, problem):
        return next(
            f
            for f in data.findings()
            if (f["uid_a"], f["uid_b"], f["problem_index"]) == (a, b, problem)
        )

    assert data.judge_finding(finding("a", "c", 2), "cheater", quick=True) == 3
    assert {data.person(uid)["mark"] for uid in "ac"} == {"cheater"}
    assert finding("b", "c", 0)["status"] == "已核查"
    # 改判为存疑：两人降为存疑，当初随他们一并处理的线索回到待复核。
    data.judge_finding(finding("a", "c", 2), "suspect")
    assert data.person("a")["mark"] == "suspect"
    assert finding("a", "b", 0)["status"] == "待复核"
    assert finding("b", "c", 0)["status"] == "待复核"
    data.judge_finding(finding("a", "c", 2), "")
    assert finding("a", "c", 2)["status"] == "待复核"
    assert data.person("a")["mark"] == "" and data.person("c")["mark"] == ""


def test_ranking_table_columns_and_export_copies_path(tmp_path, monkeypatch):
    from ojaudit.tui import ranking_screen
    from ojaudit.tui.ranking_screen import TABLE, RankingScreen

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    copied = []
    monkeypatch.setattr(ranking_screen, "copy_to_clipboard", lambda app, text: copied.append(text))
    local, data = _fixture(tmp_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test(size=(160, 40)) as pilot:
            app.push_screen(RankingScreen(data))
            await pilot.pause()
            screen = app.screen
            head = screen.query_one("#ranking-main .thead", Static)
            assert "标记" not in str(head.render()), "没有任何标记时不显示标记列"
            await pilot.press("tab")
            assert app.focused.id == "ranking-table"
            screen.query_one("#ranking-table", ListView).index = 0
            await pilot.press("enter")
            await pilot.pause()
            assert screen.table_options().per_problem
            assert " A " in f" {head.render()} " and "总分" in str(head.render())
            formats = [name for name, _, _ in TABLE].index("导出格式")
            screen.table_indices[formats] = 2  # CSV
            await pilot.press("e")
            await pilot.pause()
            assert copied and copied[0].endswith("ranking.csv")
            header = Path(copied[0]).read_text(encoding="utf-8-sig").splitlines()[0]
            assert header.split(",")[:4] == ["名次", "姓名", "UID", "A"]

    asyncio.run(scenario())


def test_people_multi_select_opens_comparison(tmp_path, monkeypatch):
    from ojaudit.tui.review_screens import CompareScreen, PeopleScreen

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local, data = _fixture(tmp_path)

    async def scenario():
        app = AuditApp(local)
        async with app.run_test(size=(150, 36)) as pilot:
            app.push_screen(PeopleScreen(data, "首页"))
            await pilot.pause()
            screen = app.screen
            uids = [row["uid"] for row in screen.rows]
            view = screen.query_one("#items", ListView)
            view.index = uids.index("a")
            await pilot.press("space")
            view.index = uids.index("b")
            await pilot.press("space")
            await pilot.pause()
            assert screen.picked == ["a", "b"]
            assert "已选 2 人" in screen.subtitle()
            await pilot.press("enter")
            await pilot.pause()
            compare = app.screen
            assert isinstance(compare, CompareScreen)
            assert compare.uids == ["a", "b"]
            assert len(compare.query(".compare-pane")) == 2
            first = compare.query_one("#compare-0")
            assert "相同" in str(first.border_subtitle)
            problem = compare.position
            await pilot.press("down")
            assert compare.position == (problem + 1) % len(compare.problems)
            await pilot.press("left")
            await pilot.pause()
            assert app.screen is screen
            await pilot.press("x")
            assert screen.picked == []

    asyncio.run(scenario())
