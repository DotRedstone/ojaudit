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
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, ListView, Static

from ojaudit.core.schema import Contest
from ojaudit.tui.contest_list_data import contest_list_description
from ojaudit.tui.data import LocalContests
from ojaudit.tui.icons import breadcrumb, label
from ojaudit.tui.interaction import Breadcrumb, SearchDialog
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView as NavigationListView


class ShellScreen(Screen):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,left,h", "back", "返回"),
        ("j,down", "down", "下移"),
        ("k,up", "up", "上移"),
        ("g", "first", "首项"),
        ("shift+g", "last", "末项"),
        ("enter,l,right,space", "open", "进入"),
        ("slash", "search", "搜索"),
    ]
    TITLE = ""
    PATH = "首页"

    HINTS = "Enter 打开  Esc 返回  / 搜索  j/k 移动"

    def breadcrumb_text(self) -> str:
        return self.PATH + (f"    {self.HINTS}" if self.app.key_hints and self.HINTS else "")

    def refresh_breadcrumb(self) -> None:
        self.query_one("#breadcrumb", Static).update(self.breadcrumb_text())

    def shell(self, content: list[object]) -> ComposeResult:
        yield Breadcrumb(self.breadcrumb_text(), id="breadcrumb")
        with Vertical(id="pane"):
            yield from content
        yield Static("", id="status")

    def on_mount(self) -> None:
        pane = self.query_one("#pane", Vertical)
        pane.border_title = self.TITLE
        self.refresh_count()
        self._update_status()
        for view in self.query(ListView):
            view.focus()
            break

    def refresh_count(self) -> None:
        view = next(iter(self.query(ListView)), None)
        if view is not None:
            self.query_one("#pane", Vertical).border_subtitle = f"{len(view.children)} 项"

    def _update_status(self) -> None:
        current = getattr(self, "CURRENT", self.TITLE)
        contest = getattr(self, "contest", None)
        contest_id = str(contest.contest_id) if contest is not None else "—"
        if getattr(self.app, "job_running", False):
            current = f"{current} · {self.app.job_status}"
        self.query_one("#status", Static).update(self.app.status_line(current, contest_id))

    def on_screen_resume(self) -> None:
        self._update_status()

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()

    def _list(self) -> ListView | None:
        return next(iter(self.query(ListView)), None)

    def action_down(self) -> None:
        view = self._list()
        if view is not None and view.children:
            view.index = min((view.index or 0) + 1, len(view.children) - 1)

    def action_up(self) -> None:
        view = self._list()
        if view is not None and view.children:
            view.index = max((view.index or 0) - 1, 0)

    def action_first(self) -> None:
        view = self._list()
        if view is not None and view.children:
            view.index = 0

    def action_last(self) -> None:
        view = self._list()
        if view is not None and view.children:
            view.index = len(view.children) - 1

    def action_open(self) -> None:
        view = self._list()
        if view is not None and view.children:
            self.open_index(view.index if view.index is not None else 0)

    def action_search(self) -> None:
        if self._list() is not None:
            self.app.push_screen(SearchDialog(), self._search_result)

    def _search_result(self, query: str | None) -> None:
        view = self._list()
        if view is None or not query:
            return
        for index, item in enumerate(view.children):
            if query.casefold() in str(item.query_one(Label).render()).casefold():
                view.index = index
                view.focus()
                return
        self.notify("未找到匹配项", severity="warning")

    def open_index(self, index: int) -> None:
        raise NotImplementedError

    @on(NavigationListView.Activated)
    def activated(self, event: NavigationListView.Activated) -> None:
        self.open_index(event.index)


class EntryDialog(ModalScreen[str | None]):
    """比赛 ID / Cookie 输入框；Cookie 仅通过密码输入控件传递。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消", priority=True),
        Binding("h", "cancel", "取消"),
    ]


    def __init__(self, *, login: bool = False) -> None:
        super().__init__()
        self.login = login

    def compose(self) -> ComposeResult:
        with Vertical(id="entry-dialog", classes="dialog-box"):
            yield Label(
                label(
                    "login" if self.login else "contest",
                    "牛客 Cookie（输入内容隐藏）" if self.login else "比赛 ID（本地查找）",
                    self.app.nerd_font,
                )
            )
            yield Input(
                placeholder="粘贴 Cookie" if self.login else "输入比赛 ID",
                password=self.login,
                id="entry-value",
            )
            with Horizontal(id="entry-buttons"):
                yield Button(
                    label(
                        "save" if self.login else "open",
                        "保存" if self.login else "打开",
                        self.app.nerd_font,
                    ),
                    id="entry-confirm",
                    variant="primary",
                )
                yield Button(label("cancel", "取消", self.app.nerd_font), id="entry-cancel")

    def on_mount(self) -> None:
        self.query_one("#entry-value", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def submit_input(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

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
    OPTIONS = ("比赛列表", "打开比赛 ID", "账户 / 登录", "设置", "待复核", "采集比赛 ID")
    ICON_KEYS = ("list", "open", "login", "settings", "pending", "collect")

    def compose(self) -> ComposeResult:
        hint = (
            "本地数据库不存在：先运行 ojaudit login，再运行 ojaudit collect <比赛ID>。"
            if not self.app.contests.db_path.is_file()
            else ""
        )
        entries = self.app.contests.list_contests(show_all=True)
        overview = Static(
            "◈ ojaudit / review\n"
            "本地优先的训练赛证据审核工作台\n"
            f"本地比赛 {len(entries)}  ·  请通过 ojaudit login 管理登录",
            id="home-overview",
        )
        items: list[object] = [
            overview,
            Static(hint),
            NavigationListView(
                *(
                    ListItem(Label(label(key, item, self.app.nerd_font)))
                    for key, item in zip(self.ICON_KEYS, self.OPTIONS)
                )
            ),
        ]
        if not self.app.contests.list_contests(show_all=True):
            items.append(
                Static(
                    "首次使用：ojaudit login → ojaudit collect <比赛ID> "
                    "→ ojaudit analyze <比赛ID> → ojaudit",
                    id="empty-guide",
                )
            )
        yield from self.shell(items)

    def open_index(self, index: int) -> None:
        if index == 0:
            self.app.push_screen(ContestListScreen(self.app.contests))
        elif index == 1:
            self.app.push_screen(EntryDialog(), self.open_contest_id)
        elif index == 2:
            from ojaudit.tui.account_screen import AccountScreen

            self.app.push_screen(AccountScreen())
        elif index == 3:
            from ojaudit.tui.settings_model import SettingsModel
            from ojaudit.tui.settings_screen import SettingsScreen

            self.app.push_screen(SettingsScreen(SettingsModel(db_path=self.app.contests.db_path)))
        elif index == 4:
            from ojaudit.tui.pending_screen import PendingScreen

            self.app.push_screen(PendingScreen())
        elif index == 5:
            self.app.push_screen(EntryDialog(), self.collect_contest_id)

    def collect_contest_id(self, raw: str | None) -> None:
        if raw is not None and raw.strip():
            self.app.start_workflow(raw.strip(), "collect_analyze")

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
            self.app.push_screen(MissingContestScreen(cid))

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
    TITLE = "比赛列表"
    HINTS = "Enter 打开  Esc 返回  / 搜索  j/k 移动  a 全部  c 采集  A 分析  x 取消"
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
        yield from self.shell(
            [
                Button("采集比赛 ID", id="collect-contest"),
                Button("分析当前选中比赛", id="analyze-contest"),
                Button("取消当前后台任务", id="cancel-task"),
                NavigationListView(id="contests"),
            ]
        )

    def on_mount(self) -> None:
        self.refresh_entries()
        super().on_mount()

    def refresh_entries(self) -> None:
        self.entries = self.contests.list_contests(self.show_all)
        view = self.query_one("#contests", ListView)
        view.clear()
        for entry in self.entries:
            text = (
                f"{entry.contest.name}  [{entry.contest.platform}/{entry.contest.contest_id}]"
                f" · {contest_list_description(self.contests, entry.contest)}"
            )
            label_text = label("contest", text, self.app.nerd_font)
            if not entry.visible:
                label_text += "  · " + label("hidden", "规则外", self.app.nerd_font)
            view.append(ListItem(Label(label_text)))
        if not self.entries:
            view.append(
                ListItem(Label("暂无比赛：先执行 ojaudit login，再执行 ojaudit collect <比赛ID>"))
            )
        view.call_after_refresh(setattr, view, "index", 0)
        self.query_one("#breadcrumb", Static).update(
            self.breadcrumb_text() + (" · 全部" if self.show_all else " · 已筛选")
        )
        self.refresh_count()

    @on(Button.Pressed, "#collect-contest")
    def collect_pressed(self, _event: Button.Pressed) -> None:
        self.app.push_screen(EntryDialog(), self.collect_id)

    def collect_id(self, cid: str | None) -> None:
        if cid is not None and cid.strip():
            self.app.start_workflow(cid.strip(), "collect_analyze")

    @on(Button.Pressed, "#analyze-contest")
    def analyze_pressed(self, _event: Button.Pressed) -> None:
        view = self.query_one("#contests", ListView)
        index = view.index if view.index is not None else 0
        if not 0 <= index < len(self.entries):
            self.notify("请先选择已有比赛", severity="warning")
            return
        contest = self.entries[index].contest
        self.app.start_workflow(contest.contest_id, "analyze", contest.platform)

    @on(Button.Pressed, "#cancel-task")
    def cancel_pressed(self, _event: Button.Pressed) -> None:
        self.app.cancel_workflow()

    def on_workflow_finished(self) -> None:
        self.refresh_entries()
        self._update_status()

    def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.refresh_entries()

    def open_index(self, index: int) -> None:
        if index < len(self.entries):
            self.app.push_screen(ContestOverviewScreen(self.entries[index].contest, self.contests))


class ContestOverviewScreen(ShellScreen):
    TITLE = "比赛总览"
    HINTS = "Enter 打开  Esc 返回  j/k 移动  x 取消任务"
    OPTIONS = ("线索", "选手", "题目", "排行榜", "采集并检测", "本地分析")
    ICON_KEYS = ("findings", "people", "problems", "ranking", "collect_analyze", "analyze")

    def __init__(self, contest: Contest, contests: LocalContests):
        super().__init__()
        self.contest = contest
        self.contests = contests
        self.PATH = f"首页 › 比赛列表 › {contest.name}"
        self.CURRENT = f"{contest.platform}/{contest.contest_id}"

    def compose(self) -> ComposeResult:
        yield from self.shell(
            [
                Static("", id="summary"),
                NavigationListView(id="overview-options"),
                Button("取消当前后台任务", id="cancel-overview-job"),
            ]
        )

    def on_mount(self) -> None:
        self.refresh_overview()
        super().on_mount()

    def on_workflow_finished(self) -> None:
        self.refresh_overview()
        self._update_status()

    def on_screen_resume(self) -> None:
        self.refresh_overview()
        super().on_screen_resume()

    def refresh_overview(self) -> None:
        stats = self.contests.stats(self.contest)
        self.query_one("#summary", Static).update(
            "\n".join(
                (
                    "◈ 本地审核概览",
                    "  ·  ".join(
                        (
                            label("people", f"参赛者 {stats.participants}", self.app.nerd_font),
                            label("submissions", f"提交 {stats.submissions}", self.app.nerd_font),
                        )
                    ),
                    "  ·  ".join(
                        (
                            label("findings", f"检测线索 {stats.findings}", self.app.nerd_font),
                            label("problems", f"题目 {stats.problems}", self.app.nerd_font),
                        )
                    ),
                    "线索为待审核提示，不代表违规结论",
                )
            )
        )
        counts = (
            stats.findings,
            stats.participants,
            stats.problems,
            stats.participants,
            "运行",
            "运行",
        )
        view = self.query_one("#overview-options", ListView)
        index = view.index or 0
        view.clear()
        for key, name, count in zip(self.ICON_KEYS, self.OPTIONS, counts):
            view.append(ListItem(Label(label(key, f"{name} · {count}", self.app.nerd_font))))
        view.call_after_refresh(setattr, view, "index", index)
        self.refresh_count()

    @on(Button.Pressed, "#cancel-overview-job")
    def cancel_pressed(self, _event: Button.Pressed) -> None:
        self.app.cancel_workflow()

    def open_index(self, index: int) -> None:
        from ojaudit.tui.review_data import ReviewData
        from ojaudit.tui.review_screens import FindingsScreen, PeopleScreen, ProblemsScreen

        if index == 4:
            self.app.start_workflow(self.contest.contest_id, "collect_analyze")
            return
        if index == 5:
            self.app.start_workflow(self.contest.contest_id, "analyze", self.contest.platform)
            return
        if index not in (0, 1, 2, 3):
            return
        if index == 3:
            from ojaudit.tui.ranking_screen import RankingScreen

            self.app.push_screen(RankingScreen(ReviewData(self.contests, self.contest)))
            return
        data = ReviewData(self.contests, self.contest)
        screen_type = (FindingsScreen, PeopleScreen, ProblemsScreen)[index]
        self.app.push_screen(screen_type(data, self.PATH))


class MissingContestScreen(ShellScreen):
    """没有本地数据时保留可操作的采集引导。"""

    TITLE = "本地缺少比赛"
    HINTS = "Enter 选择  Esc 返回  j/k 移动"
    OPTIONS = ("采集并检测", "仅采集", "返回")

    def __init__(self, contest_id: str) -> None:
        super().__init__()
        self.contest_id = contest_id
        self.PATH = f"首页 › 比赛 {contest_id} › 未采集"

    def compose(self) -> ComposeResult:
        yield from self.shell(
            [
                Static(
                    f"比赛 {self.contest_id} 尚未在本地数据库中。"
                    f"可选择采集，或运行 ojaudit collect {self.contest_id}。",
                ),
                NavigationListView(*(ListItem(Label(item)) for item in self.OPTIONS)),
            ]
        )

    def open_index(self, index: int) -> None:
        if index == 0:
            self.app.start_workflow(self.contest_id, "collect_analyze")
        elif index == 1:
            self.app.start_workflow(self.contest_id, "collect")
        else:
            self.app.pop_screen()
