"""
Module: TUI / screens
Description: 统一页面外壳、表格列表基类，以及首页、比赛列表与比赛总览。
Scope: TUI
Notes:
- 每个页面由「顶栏路径 + 标题 + 内容 + 按键提示栏」组成，提示栏只列本页关键操作。
- 详情页由 review_screens 实现；本模块不写数据库。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Label, ListView, Static

from ojaudit.core.schema import Contest
from ojaudit.tui import ui
from ojaudit.tui.contest_list_data import ContestSummary, contest_summary
from ojaudit.tui.data import LocalContests
from ojaudit.tui.icons import breadcrumb, glyph, label
from ojaudit.tui.interaction import Breadcrumb
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView as NavigationListView
from ojaudit.tui.popup import ConfirmPopup, InputPopup, SearchLine
from ojaudit.tui.splitter import Splitter

NAV_HINTS: tuple[tuple[str, str], ...] = (("↵", "打开"), ("esc", "返回"), ("/", "搜索"))


# 提示栏上显示的按键 → 点击时模拟的按键。
KEY_PRESS = {
    "↵": "enter",
    "esc": "escape",
    "/": "slash",
    "?": "question_mark",
    "space": "space",
    "tab": "tab",
    "←→": "right",
    "[": "left_square_bracket",
    "]": "right_square_bracket",
    "h/l": "l",
}


class KeyBar(Static):
    """底部提示栏：每个提示都可以用鼠标点击，等同于按下对应按键。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self.spans: list[tuple[int, int, str]] = []

    def show(self, hints: Sequence[tuple[str, str]], right: str) -> None:
        colors = ui.palette(self.app)
        text = Text(no_wrap=True)
        self.spans = []
        for index, (key, action) in enumerate(hints):
            if index:
                text.append("   ")
            start = text.cell_len
            text.append(key, style=f"bold {colors.accent}")
            text.append(f" {action}", style=colors.muted)
            press = KEY_PRESS.get(key, key.split("/")[0])
            self.spans.append((start, text.cell_len, press))
        gap = self.size.width - text.cell_len - len(right) - 2
        if gap > 0:
            text.append(" " * gap)
            text.append(right, style=colors.muted)
        self.update(text)

    def on_click(self, event: events.Click) -> None:
        for start, end, key in self.spans:
            if start <= event.x - 1 < end:
                event.stop()
                self.app.simulate_key(key)
                return


class Chrome:
    """顶栏与提示栏渲染；所有全屏页面共用，保证位置和配色一致。"""

    PATH = "首页"
    HINTS: ClassVar[Sequence[tuple[str, str]]] = NAV_HINTS

    def chrome_top(self) -> ComposeResult:
        yield Breadcrumb("", id="breadcrumb")

    def chrome_bottom(self) -> ComposeResult:
        yield KeyBar(id="status")

    def _update_status(self) -> None:
        app: Any = self.app  # type: ignore[attr-defined]
        colors = ui.palette(app)
        width = app.size.width
        top = Text(no_wrap=True)
        top.append(" ", style=f"on {colors.accent}")
        top.append(
            label("home", "ojaudit", app.nerd_font) + " ",
            style=f"bold {colors.bg} on {colors.accent}",
        )
        top.append("  ")
        parts = breadcrumb(self.PATH, app.nerd_font).split(" › ")
        for index, part in enumerate(parts):
            if index:
                top.append(" › ", style=colors.muted)
            last = index == len(parts) - 1
            top.append(part, style=f"bold {colors.fg}" if last else colors.muted)
        busy = app.job_running
        right = Text(style=colors.warn if busy else colors.muted)
        right.append("● " + str(app.job_status))
        if busy and app.job_progress is not None:
            _stage, done, total, _ = app.job_progress
            right.append("  ")
            if total:
                right.append_text(ui.bar(done / total, 16, colors.warn, colors.surface))
                right.append(" ")
            right.append(app.progress_text(), style=colors.fg)
            right.append("  x 取消", style=colors.muted)
        gap = width - top.cell_len - right.cell_len - 2
        crumb = self.query_one("#breadcrumb", Breadcrumb)  # type: ignore[attr-defined]
        crumb.job_x = width
        if gap > 0:
            top.append(" " * gap)
            crumb.job_x = top.cell_len
            top.append_text(right)
        crumb.update(top)
        hints = list(self.HINTS) + [("?", "帮助")]
        if not app.key_hints:
            hints = [("?", "帮助")]
        self.query_one("#status", KeyBar).show(hints, str(app.theme_name))  # type: ignore[attr-defined]


class ShellScreen(Chrome, Screen):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,left,h", "back", "返回"),
        ("j,down", "down", "下移"),
        ("k,up", "up", "上移"),
        ("g", "first", "首项"),
        ("shift+g", "last", "末项"),
        ("enter,l,right,space", "open", "打开"),
        ("slash", "search", "搜索"),
    ]
    TITLE = ""

    def heading(self) -> Text:
        """页面标题行：粗体标题 + 弱化的副标题。"""
        colors = ui.palette(self.app)
        text = Text(self.TITLE, style=f"bold {colors.fg}")
        subtitle = self.subtitle()
        if subtitle:
            text.append("   " + subtitle, style=colors.muted)
        return text

    def subtitle(self) -> str:
        return ""

    def shell(self, content: list[object]) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            yield Static("", id="heading")
            yield from content  # type: ignore[misc]
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
        self.refresh_chrome()
        for view in self.query(ListView):
            view.focus()
            break

    def refresh_chrome(self) -> None:
        for heading in self.query("#heading"):
            heading.update(self.heading())  # type: ignore[attr-defined]
        self._update_status()

    def on_resize(self, _event: events.Resize) -> None:
        self.call_after_refresh(self.on_layout_change)

    def on_layout_change(self) -> None:
        self.refresh_chrome()

    def on_screen_resume(self) -> None:
        self.refresh_chrome()

    def action_back(self) -> None:
        # 栈底是 Textual 默认屏和首页，首页不能被弹出（否则界面变空，再按 q 会崩溃）。
        if len(self.app.screen_stack) > 2 and not isinstance(self, HomeScreen):
            self.app.pop_screen()

    def _list(self) -> ListView | None:
        focused = self.app.focused
        if isinstance(focused, ListView):
            return focused
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
        view = self._list()
        if view is None:
            return
        self._search_origin = view.index
        self.app.push_screen(SearchLine(self._jump_to), self._search_result)

    def _jump_to(self, query: str) -> bool:
        view = self._list()
        if view is None:
            return False
        for index, item in enumerate(view.children):
            if query.casefold() in str(item.query_one(Label).render()).casefold():
                view.index = index
                return True
        return False

    def _search_result(self, query: str | None) -> None:
        view = self._list()
        if view is None:
            return
        if query is None:
            view.index = getattr(self, "_search_origin", view.index)
        elif query and not self._jump_to(query):
            self.notify(f"未找到：{query}", severity="warning")
        view.focus()

    def open_index(self, index: int) -> None:
        raise NotImplementedError

    @on(NavigationListView.Activated)
    def activated(self, event: NavigationListView.Activated) -> None:
        self.open_index(event.index)


class TableScreen(ShellScreen):
    """带表头的单列表页：子类声明列与每行单元格，基类负责对齐和保持选中位置。"""

    COLUMNS: ClassVar[Sequence[ui.Column]] = ()
    EMPTY = "暂无数据"

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Any] = []

    def table(self) -> list[object]:
        return [Static("", classes="thead"), NavigationListView(id="items")]

    def compose(self) -> ComposeResult:
        yield from self.shell(self.table())

    def on_mount(self) -> None:
        self.reload()
        super().on_mount()

    def on_screen_resume(self) -> None:
        self.reload()
        super().on_screen_resume()

    def on_layout_change(self) -> None:
        self.reload()
        super().on_layout_change()

    def items(self) -> list[Any]:
        return []

    def cells(self, row: Any) -> Sequence[str | Text]:
        return [str(row)]

    def row_width(self) -> int:
        return max(self.app.size.width - 8, 40)

    def reload(self) -> None:
        colors = ui.palette(self.app)
        width = self.row_width()
        self.query_one(".thead", Static).update(ui.table_header(self.COLUMNS, width, colors.muted))
        view = self.query_one("#items", ListView)
        previous = view.index or 0
        self.rows = self.items()
        view.clear()
        for row in self.rows:
            view.append(ListItem(Label(ui.table_row(self.cells(row), self.COLUMNS, width))))
        if not self.rows:
            view.append(ListItem(Label(Text(self.EMPTY, style=colors.muted))))
        view.call_after_refresh(setattr, view, "index", max(0, min(previous, len(self.rows) - 1)))
        self.refresh_chrome()

    def selected_row(self, index: int) -> Any:
        return self.rows[index] if 0 <= index < len(self.rows) else None


class EntryDialog(InputPopup):
    """比赛 ID / Cookie 输入；Cookie 仅经密码输入框传递。"""

    def __init__(self, *, login: bool = False, title: str = "") -> None:
        super().__init__(
            title or ("粘贴牛客 Cookie" if login else "打开本地比赛"),
            placeholder="Cookie" if login else "比赛 ID，例如 90001",
            password=login,
            note="只保存到本机配置目录（0600），界面不显示" if login else "",
            validate=None if login else _validate_contest_id,
            input_id="entry-value",
        )


def _validate_contest_id(value: str) -> str | None:
    text = value.strip()
    if text and not text.replace("-", "").replace("_", "").isalnum():
        return "比赛 ID 只能包含字母、数字、- 和 _"
    return None


def _menu_row(icon: str, name: str, detail: str, width: int, app: Any) -> Text:
    colors = ui.palette(app)
    mark = glyph(icon, app.nerd_font)
    left = Text((mark + "  " if mark else "") + name, style=colors.fg)
    return ui.table_row(
        [left, Text(detail, style=colors.muted)],
        (ui.Column(""), ui.Column("", 14, "right")),
        width,
    )


class HomeScreen(ShellScreen):
    TITLE = "首页"
    PATH = "首页"
    HINTS = (("↵", "打开"), ("q", "退出"), ("t", "主题"))
    OPTIONS = ("比赛列表", "打开比赛 ID", "账户与登录", "设置", "待复核", "采集新比赛")
    ICON_KEYS = ("list", "open", "login", "settings", "pending", "collect")
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("c", "collect", "采集新比赛"),
        ("o", "open_id", "打开比赛 ID"),
    ]

    def compose(self) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            yield Static("", id="hero")
            with Horizontal(id="home-columns"):
                with Vertical(id="home-menu", classes="panel"):
                    yield NavigationListView(
                        *(ListItem(Label(name)) for name in self.OPTIONS), id="menu"
                    )
                yield Splitter("home-menu", "home", minimum=24)
                yield Static("", id="home-overview", classes="panel")
            yield Static("", id="home-recent")
            if not self.app.contests.list_contests(show_all=True):
                yield Static(
                    "首次使用：ojaudit login → ojaudit collect <比赛ID> "
                    "→ ojaudit analyze <比赛ID> → ojaudit",
                    id="empty-guide",
                )
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
        self.query_one("#home-menu").border_title = "开始"
        self.query_one("#home-overview").border_title = "概况"
        self.refresh_home()
        super().on_mount()

    def on_screen_resume(self) -> None:
        self.refresh_home()
        super().on_screen_resume()

    def on_workflow_finished(self) -> None:
        self.refresh_home()

    def on_layout_change(self) -> None:
        self.refresh_home()
        super().on_layout_change()

    def refresh_home(self) -> None:
        from ojaudit.tui.account_service import logged_in_locally
        from ojaudit.tui.workflow import pending_entries

        colors = ui.palette(self.app)
        contests = self.app.contests.list_contests(show_all=True)
        pending = pending_entries(self.app.contests) if contests else []
        findings = sum(entry.kind == "finding" for entry in pending)
        suspects = len(pending) - findings

        hero = Text("ojaudit", style=f"bold {colors.accent}")
        hero.append("  训练赛代码审查工作台\n", style=colors.fg)
        hero.append("检测结果只是复核线索，不等于违规认定。", style=colors.muted)
        self.query_one("#hero", Static).update(hero)

        details = (
            f"{len(contests)} 场" if contests else "",
            "",
            "",
            "",
            f"{findings} 条" if findings else "",
            "",
        )
        menu = self.query_one("#menu", ListView)
        width = max(menu.size.width - 4, 24)
        for item, icon, name, detail in zip(menu.children, self.ICON_KEYS, self.OPTIONS, details):
            item.query_one(Label).update(_menu_row(icon, name, detail, width, self.app))

        db = self.app.contests.db_path
        try:
            shown = "~/" + str(db.relative_to(db.home()))
        except ValueError:
            shown = str(db)
        rows = (
            ("本地比赛", str(len(contests)), colors.fg),
            ("待复核线索", str(findings), colors.warn if findings else colors.fg),
            ("存疑选手", str(suspects), colors.caution if suspects else colors.fg),
            (
                "牛客登录",
                "已保存 Cookie" if logged_in_locally() else "未登录",
                colors.ok if logged_in_locally() else colors.muted,
            ),
            ("数据库", shown if db.is_file() else "尚未创建", colors.muted),
        )
        overview = Text()
        for index, (name, value, color) in enumerate(rows):
            if index:
                overview.append("\n")
            overview.append_text(ui.fit(Text(name, style=colors.muted), 12))
            overview.append(value, style=color)
        self.query_one("#home-overview", Static).update(overview)

        recent = Text()
        if contests:
            columns = (
                ui.Column("最近比赛"),
                ui.Column("状态", 8),
                ui.Column("实锤 强 疑", 10),
                ui.Column("复核", 14),
            )
            total = max(self.app.size.width - 10, 60)
            recent.append_text(ui.table_header(columns, total, colors.muted))
            for entry in contests[:8]:
                summary = contest_summary(self.app.contests, entry.contest)
                recent.append("\n")
                recent.append_text(
                    ui.table_row(
                        [
                            Text(entry.contest.name, style=colors.fg),
                            state_text(summary, colors),
                            level_counts(summary, colors),
                            ui.progress(summary.reviewed, summary.findings, colors, 6),
                        ],
                        columns,
                        total,
                    )
                )
        self.query_one("#home-recent", Static).update(recent)

    def open_index(self, index: int) -> None:
        if index == 0:
            self.app.push_screen(ContestListScreen(self.app.contests))
        elif index == 1:
            self.action_open_id()
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
            self.action_collect()

    def action_open_id(self) -> None:
        self.app.push_screen(EntryDialog(), self.open_contest_id)

    def action_collect(self) -> None:
        self.app.push_screen(EntryDialog(title="采集新比赛"), self.collect_contest_id)

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


def level_counts(summary: ContestSummary, colors: ui.Palette) -> Text:
    if not summary.findings:
        return Text("—", style=colors.muted)
    text = Text()
    for count, color in zip(summary.levels, (colors.danger, colors.warn, colors.caution)):
        if text:
            text.append(" ")
        text.append(f"{count:>2}", style=f"bold {color}" if count else colors.muted)
    return text


def state_text(summary: ContestSummary, colors: ui.Palette) -> Text:
    color = {"已分析": colors.ok, "已采集": colors.accent}.get(summary.state, colors.muted)
    return ui.dot(summary.state, color)


class ContestListScreen(TableScreen):
    TITLE = "比赛列表"
    PATH = "首页 › 比赛列表"
    HINTS = (
        ("↵", "打开"),
        ("c", "采集"),
        ("R", "重新分析"),
        ("S", "同步"),
        ("a", "显示被过滤的"),
        ("/", "搜索"),
    )
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("a", "toggle_all", "显示全部 / 仅筛选"),
        ("c", "collect", "采集新比赛"),
        ("R", "analyze", "重新分析所选比赛"),
        ("x", "cancel_job", "取消后台任务"),
        ("S", "sync", "同步已参加的比赛"),
    ]
    COLUMNS = (
        ui.Column("比赛"),
        ui.Column("ID", 10),
        ui.Column("日期", 10),
        ui.Column("提交", 6, "right"),
        ui.Column("状态", 8),
        ui.Column("实锤 强 疑", 10),
        ui.Column("复核", 14),
    )
    EMPTY = "暂无比赛：登录后按 S 同步你参加过的比赛，或按 c 输入比赛 ID 采集"

    def __init__(self, contests: LocalContests):
        super().__init__()
        self.contests = contests
        self.show_all = False
        self.hidden_count = 0
        self.summaries: dict[tuple[str, str], ContestSummary] = {}

    @property
    def entries(self) -> list[Any]:
        return self.rows

    def subtitle(self) -> str:
        hidden = self.hidden_count
        if self.show_all:
            return f"{len(self.rows)} 场 · 含被过滤的 {hidden} 场"
        return f"{len(self.rows)} 场" + (f" · 已过滤 {hidden} 场（a 显示）" if hidden else "")

    def on_mount(self) -> None:
        super().on_mount()
        self.app.sync_joined()

    def action_sync(self) -> None:
        self.app.sync_joined(force=True)

    def items(self) -> list[Any]:
        everything = self.contests.list_contests(show_all=True)
        self.hidden_count = sum(not entry.visible for entry in everything)
        entries = everything if self.show_all else [e for e in everything if e.visible]
        self.summaries = {
            (e.contest.platform, e.contest.contest_id): contest_summary(self.contests, e.contest)
            for e in entries
        }
        return entries

    def cells(self, row: Any) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        contest = row.contest
        summary = self.summaries[(contest.platform, contest.contest_id)]
        name = Text(contest.name, style=colors.fg)
        if not row.visible:
            name.append("  规则外", style=colors.muted)
        return [
            name,
            Text(contest.contest_id, style=colors.muted),
            Text(summary.date, style=colors.muted),
            str(summary.submissions),
            state_text(summary, colors),
            level_counts(summary, colors),
            ui.progress(summary.reviewed, summary.findings, colors, 6),
        ]

    def refresh_entries(self) -> None:
        self.reload()

    def action_collect(self) -> None:
        self.app.push_screen(EntryDialog(title="采集新比赛"), self.collect_id)

    def collect_id(self, cid: str | None) -> None:
        if cid is not None and cid.strip():
            self.app.start_workflow(cid.strip(), "collect_analyze")

    def action_analyze(self) -> None:
        view = self.query_one("#items", ListView)
        row = self.selected_row(view.index if view.index is not None else 0)
        if row is None:
            self.notify("请先选择已有比赛", severity="warning")
            return
        self.app.start_workflow(row.contest.contest_id, "analyze", row.contest.platform)

    def action_cancel_job(self) -> None:
        self.app.cancel_workflow()

    def on_workflow_finished(self) -> None:
        self.reload()

    def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.reload()

    def open_index(self, index: int) -> None:
        row = self.selected_row(index)
        if row is None:
            return
        summary = self.summaries.get((row.contest.platform, row.contest.contest_id))
        if summary is not None and summary.state == "未采集":
            contest = row.contest
            self.app.push_screen(
                ConfirmPopup(
                    "采集比赛", f"「{contest.name}」还没有采集。\n现在采集并检测？", default=True
                ),
                lambda ok: (
                    ok
                    and self.app.start_workflow(
                        contest.contest_id, "collect_analyze", contest.platform
                    )
                ),
            )
            return
        self.app.push_screen(ContestOverviewScreen(row.contest, self.contests))


class ContestOverviewScreen(ShellScreen):
    TITLE = "比赛总览"
    HINTS = (("↵", "打开"), ("esc", "返回"), ("c", "重新采集"), ("R", "重新分析"))
    OPTIONS = ("线索", "选手", "题目", "排行榜")
    ICON_KEYS = ("findings", "people", "problems", "ranking")
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("c", "collect", "重新采集并检测"),
        ("R", "analyze", "重新本地分析"),
        ("x", "cancel_job", "取消后台任务"),
    ]

    def __init__(self, contest: Contest, contests: LocalContests):
        super().__init__()
        self.contest = contest
        self.contests = contests
        self.PATH = f"首页 › 比赛列表 › {contest.name}"
        self.TITLE = contest.name

    def compose(self) -> ComposeResult:
        yield from self.shell(
            [
                Horizontal(
                    *(Static("", id=f"card-{i}", classes="card") for i in range(5)),
                    id="cards",
                ),
                Static("", id="summary"),
                NavigationListView(
                    *(ListItem(Label(name)) for name in self.OPTIONS), id="overview-options"
                ),
            ]
        )

    def on_mount(self) -> None:
        self.refresh_overview()
        super().on_mount()

    def on_workflow_finished(self) -> None:
        self.refresh_overview()

    def on_screen_resume(self) -> None:
        self.refresh_overview()
        super().on_screen_resume()

    def on_layout_change(self) -> None:
        self.refresh_overview()
        super().on_layout_change()

    def subtitle(self) -> str:
        summary = getattr(self, "summary", None)
        extra = f" · {summary.date} · {summary.state}" if summary else ""
        return f"{self.contest.platform}/{self.contest.contest_id}{extra}"

    def refresh_overview(self) -> None:
        colors = ui.palette(self.app)
        summary = contest_summary(self.contests, self.contest)
        self.summary = summary
        stats = summary.stats

        def card(index: int, value: Text | str, caption: str) -> None:
            body = Text()
            if isinstance(value, Text):
                body.append_text(value)
            else:
                body.append(value, style=f"bold {colors.fg}")
            body.append("\n" + caption, style=colors.muted)
            self.query_one(f"#card-{index}", Static).update(body)

        card(0, str(stats.participants), "参赛者")
        card(1, str(stats.submissions), "提交")
        card(2, str(stats.problems), "题目")
        levels = Text()
        for count, name, color in zip(
            summary.levels, ("实锤", "中强", "存疑"), (colors.danger, colors.warn, colors.caution)
        ):
            if levels:
                levels.append("  ")
            levels.append(str(count), style=f"bold {color}" if count else colors.muted)
            levels.append(" " + name, style=colors.muted)
        card(3, levels if summary.findings else Text("0", style=f"bold {colors.fg}"), "检测线索")
        card(4, ui.progress(summary.reviewed, summary.findings, colors, 10), "人工复核")
        self.query_one("#summary", Static).update(
            Text(
                f"参赛者 {stats.participants} · 提交 {stats.submissions} · "
                f"题目 {stats.problems} · 线索 {stats.findings}",
                style=colors.muted,
            )
        )

        details = (
            f"{summary.findings} 条 · {summary.findings - summary.reviewed} 待复核"
            if summary.findings
            else ("尚未分析，按 R 运行" if summary.state != "已分析" else "无线索"),
            f"{stats.participants} 人 · {summary.marked} 已标记",
            f"{stats.problems} 题",
            "本地推导，非官方",
        )
        view = self.query_one("#overview-options", ListView)
        width = max(view.size.width - 4, 40)
        for item, icon, name, detail in zip(view.children, self.ICON_KEYS, self.OPTIONS, details):
            mark = glyph(icon, self.app.nerd_font)
            left = Text((mark + "  " if mark else "") + name, style=colors.fg)
            item.query_one(Label).update(
                ui.table_row(
                    [left, Text(detail, style=colors.muted)],
                    (ui.Column("", 16), ui.Column("")),
                    width,
                )
            )
        self.refresh_chrome()

    def action_collect(self) -> None:
        self.app.start_workflow(self.contest.contest_id, "collect_analyze")

    def action_analyze(self) -> None:
        self.app.start_workflow(self.contest.contest_id, "analyze", self.contest.platform)

    def action_cancel_job(self) -> None:
        self.app.cancel_workflow()

    def open_index(self, index: int) -> None:
        from ojaudit.tui.review_data import ReviewData
        from ojaudit.tui.review_screens import FindingsScreen, PeopleScreen, ProblemsScreen

        if index not in (0, 1, 2, 3):
            return
        data = ReviewData(self.contests, self.contest)
        if index == 3:
            from ojaudit.tui.ranking_screen import RankingScreen

            self.app.push_screen(RankingScreen(data))
            return
        screen_type = (FindingsScreen, PeopleScreen, ProblemsScreen)[index]
        self.app.push_screen(screen_type(data, self.PATH))


class MissingContestScreen(ShellScreen):
    """没有本地数据时保留可操作的采集引导。"""

    TITLE = "本地没有这场比赛"
    OPTIONS = ("采集并检测", "仅采集", "返回")

    def __init__(self, contest_id: str) -> None:
        super().__init__()
        self.contest_id = contest_id
        self.PATH = f"首页 › 比赛 {contest_id}"

    def subtitle(self) -> str:
        return f"比赛 {self.contest_id} 尚未采集；也可以运行 ojaudit collect {self.contest_id}"

    def compose(self) -> ComposeResult:
        yield from self.shell(
            [NavigationListView(*(ListItem(Label(item)) for item in self.OPTIONS))]
        )

    def open_index(self, index: int) -> None:
        if index == 0:
            self.app.start_workflow(self.contest_id, "collect_analyze")
        elif index == 1:
            self.app.start_workflow(self.contest_id, "collect")
        else:
            self.app.pop_screen()
