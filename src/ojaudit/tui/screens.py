"""
Module: TUI / screens
Description: 实现首页、比赛列表与比赛总览的分层导航。
Scope: TUI
Notes: 第七阶段详情页由 review_screens 实现，排行榜保留第八阶段入口。
"""

from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

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
        for view in self.query(ListView):
            view.focus()
            break

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


class EntryDialog(ModalScreen[str | None]):
    """比赛 ID / Cookie 输入框；Cookie 仅通过密码输入控件传递。"""

    CSS = """
    EntryDialog { align: center middle; }
    #entry-dialog { width: 68; height: auto; border: round $accent;
                    background: $panel; padding: 1 2; }
    #entry-buttons { height: auto; }
    """

    def __init__(self, *, login: bool = False) -> None:
        super().__init__()
        self.login = login

    def compose(self) -> ComposeResult:
        with Vertical(id="entry-dialog"):
            yield Label("牛客 Cookie（输入内容隐藏）" if self.login else "比赛 ID（本地查找）")
            yield Input(
                placeholder="粘贴 Cookie" if self.login else "输入比赛 ID",
                password=self.login,
                id="entry-value",
            )
            with Horizontal(id="entry-buttons"):
                yield Button("保存" if self.login else "打开", id="entry-confirm", variant="primary")
                yield Button("取消", id="entry-cancel")

    def on_mount(self) -> None:
        self.query_one("#entry-value", Input).focus()

    @on(Input.Submitted)
    def submit_input(self) -> None:
        self.dismiss(self.query_one("#entry-value", Input).value)

    @on(Button.Pressed)
    def press_button(self, event: Button.Pressed) -> None:
        self.dismiss(
            self.query_one("#entry-value", Input).value
            if event.button.id == "entry-confirm"
            else None
        )


class HomeScreen(ShellScreen):
    TITLE = "ojaudit · 首页"
    PATH = "首页"
    OPTIONS = ("比赛列表", "打开比赛 ID", "账户 / 登录", "设置")

    def compose(self) -> ComposeResult:
        yield from self.shell([ListView(*(ListItem(Label(item)) for item in self.OPTIONS))])

    def open_index(self, index: int) -> None:
        if index == 0:
            self.app.push_screen(ContestListScreen(self.app.contests))
        elif index == 1:
            self.app.push_screen(EntryDialog(), self.open_contest_id)
        elif index == 2:
            self.app.push_screen(EntryDialog(login=True), self.save_login)
        elif index == 3:
            from ojaudit.tui.settings_screen import SettingsScreen

            self.app.push_screen(SettingsScreen())

    def open_contest_id(self, raw: str | None) -> None:
        if raw is None:
            return
        cid = raw.strip()
        if not cid:
            self.notify("比赛 ID 不能为空", severity="warning")
            return
        matches = [
            entry.contest
            for entry in self.app.contests.list_contests(show_all=True)
            if entry.contest.contest_id == cid
        ]
        if len(matches) == 1:
            self.app.push_screen(ContestOverviewScreen(matches[0], self.app.contests))
        elif len(matches) > 1:
            self.notify("多个平台存在该 ID，请从比赛列表选择", severity="warning")
        else:
            self.notify(
                f"本地没有比赛 {cid}；请先运行 ojaudit collect {cid} 采集",
                severity="warning",
                timeout=8,
            )

    def save_login(self, value: str | None) -> None:
        if value is None:
            return
        from ojaudit.cli_operations import save_cookie

        try:
            save_cookie(value)
        except (OSError, ValueError):
            self.notify("Cookie 保存失败：请检查内容及配置目录权限", severity="error")
        else:
            self.notify("Cookie 已保存到本地配置目录（权限 0600）")


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
        from ojaudit.tui.review_data import ReviewData
        from ojaudit.tui.review_screens import FindingsScreen, PeopleScreen, ProblemsScreen

        if index == 3:
            from ojaudit.tui.ranking_screen import RankingScreen

            self.app.push_screen(RankingScreen(ReviewData(self.contests, self.contest)))
            return
        data = ReviewData(self.contests, self.contest)
        screen_type = (FindingsScreen, PeopleScreen, ProblemsScreen)[index]
        self.app.push_screen(screen_type(data, self.PATH))
