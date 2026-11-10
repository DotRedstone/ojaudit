"""
Module: TUI / screens
Description: 实现首页、比赛列表与比赛总览的分层导航。
Scope: TUI
Notes: 第七、八阶段的详情页暂不实现，入口只显示提示。
"""

from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Label, ListItem, ListView, Static

from ojaudit.core.schema import Contest
from ojaudit.tui.data import LocalContests


class ShellScreen(Screen):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "back", "返回"),
        ("h", "back", "返回"),
        ("j", "down", "下移"),
        ("k", "up", "上移"),
        ("g", "first", "首项"),
        ("shift+g", "last", "末项"),
        ("enter", "open", "进入"),
        ("l", "open", "进入"),
    ]
    TITLE = ""
    PATH = "首页"

    def shell(self, content: list[object]) -> ComposeResult:
        yield Static(self.PATH, id="breadcrumb")
        with Vertical(id="pane"):
            yield from content
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.query_one("#pane", Vertical).border_title = self.TITLE
        self._update_status()
        self.query_one(ListView).focus()

    def _update_status(self) -> None:
        app = self.app
        current = getattr(self, "CURRENT", self.TITLE)
        self.query_one("#status", Static).update(
            f" NORMAL  ❯  {current}   │  任务: 空闲   │  主题: {app.theme_name} "
        )

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()

    def action_down(self) -> None:
        view = self.query_one(ListView)
        if view.children:
            view.index = min((view.index or 0) + 1, len(view.children) - 1)

    def action_up(self) -> None:
        view = self.query_one(ListView)
        if view.children:
            view.index = max((view.index or 0) - 1, 0)

    def action_first(self) -> None:
        self.query_one(ListView).index = 0

    def action_last(self) -> None:
        view = self.query_one(ListView)
        if view.children:
            view.index = len(view.children) - 1

    def action_open(self) -> None:
        view = self.query_one(ListView)
        if view.children:
            self.open_index(view.index if view.index is not None else 0)

    def open_index(self, index: int) -> None:
        raise NotImplementedError

    @on(ListView.Selected)
    def selected(self, event: ListView.Selected) -> None:
        if event.list_view.index is not None:
            self.open_index(event.list_view.index)


class HomeScreen(ShellScreen):
    TITLE = "ojaudit · 首页"
    PATH = "首页"
    OPTIONS = ("比赛列表", "打开比赛 ID（后续阶段）", "账户 / 登录（后续阶段）", "设置（后续阶段）")

    def compose(self) -> ComposeResult:
        yield from self.shell([ListView(*(ListItem(Label(item)) for item in self.OPTIONS))])

    def open_index(self, index: int) -> None:
        if index == 0:
            self.app.push_screen(ContestListScreen(self.app.contests))
        else:
            self.notify("此入口将在后续阶段实现", severity="information")


class ContestListScreen(ShellScreen):
    TITLE = "比赛列表 · a 切换全部"
    PATH = "首页 › 比赛列表"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("a", "toggle_all", "切换全部"),
    ]

    def __init__(self, contests: LocalContests):
        super().__init__()
        self.contests = contests
        self.show_all = False
        self.entries = []

    def compose(self) -> ComposeResult:
        yield from self.shell([ListView(id="contests")])

    def on_mount(self) -> None:
        self.refresh_entries()
        super().on_mount()

    def refresh_entries(self) -> None:
        self.entries = self.contests.list_contests(self.show_all)
        view = self.query_one("#contests", ListView)
        view.clear()
        for entry in self.entries:
            label = f"{entry.contest.name}  [{entry.contest.platform}/{entry.contest.contest_id}]"
            if not entry.visible:
                label += "  · 规则外"
            view.append(ListItem(Label(label)))
        if not self.entries:
            view.append(ListItem(Label("暂无比赛（本地存储为空或均被规则过滤）")))
        view.call_after_refresh(setattr, view, "index", 0)
        self.query_one("#breadcrumb", Static).update(
            self.PATH + (" › 全部" if self.show_all else " › 已筛选")
        )

    def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.refresh_entries()

    def open_index(self, index: int) -> None:
        if index < len(self.entries):
            self.app.push_screen(ContestOverviewScreen(self.entries[index].contest, self.contests))


class ContestOverviewScreen(ShellScreen):
    TITLE = "比赛总览"
    OPTIONS = ("线索", "选手", "题目", "排行榜")

    def __init__(self, contest: Contest, contests: LocalContests):
        super().__init__()
        self.contest = contest
        self.contests = contests
        self.PATH = f"首页 › 比赛列表 › {contest.name}"
        self.CURRENT = f"{contest.platform}/{contest.contest_id}"

    def compose(self) -> ComposeResult:
        stats = self.contests.stats(self.contest)
        with Vertical():
            yield Static(self.PATH, id="breadcrumb")
            with Vertical(id="pane"):
                yield Static(
                    f"线索 {stats.findings}   选手 {stats.participants}   "
                    f"题目 {stats.problems}   提交 {stats.submissions}",
                    id="summary",
                )
                yield ListView(
                    *(
                        ListItem(Label(f"{name} · {count}"))
                        for name, count in zip(
                            self.OPTIONS,
                            (
                                stats.findings,
                                stats.participants,
                                stats.problems,
                                stats.participants,
                            ),
                        )
                    ),
                )
            yield Static("", id="status")

    def open_index(self, index: int) -> None:
        self.notify(f"{self.OPTIONS[index]}页面将在第七或八阶段实现", severity="information")
