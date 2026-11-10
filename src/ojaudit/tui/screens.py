"""
Module: TUI / screens
Description: 统一页面外壳、表格列表基类，以及首页、比赛列表与比赛总览。
Scope: TUI
Notes:
- 每个页面由「叠放的书页外框（标题边写页名）+ 内容 + 按键提示栏」组成，提示栏只列本页关键操作。
- 导航：→ 进入下一层，← 返回上一层，↑↓ 在同一层中移动；回车默认同 →，可复核的页面为复核。
- 详情页由 review_screens 实现；本模块不写数据库。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any, ClassVar

from rich.cells import cell_len
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
from ojaudit.tui.icons import glyph, label
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView as NavigationListView
from ojaudit.tui.popup import ConfirmPopup, InputPopup, SearchLine
from ojaudit.tui.splitter import start_drag

NAV_HINTS: tuple[tuple[str, str], ...] = (("↵", "打开"), ("←", "返回"), ("/", "搜索"))


# 提示栏上显示的按键 → 点击时模拟的按键。
KEY_PRESS = {
    "↵": "enter",
    "esc": "escape",
    "/": "slash",
    "?": "question_mark",
    "space": "space",
    "tab": "tab",
    "←→": "right",
    "←": "left",
    "→": "right",
    "↑↓": "down",
    "[": "left_square_bracket",
    "]": "right_square_bracket",
    "h/l": "l",
    "1-4": "1",
}


class KeyBar(Static):
    """底部一行：左侧是本页按键提示（可点击，等同按键），右侧是后台任务状态（点击可取消）。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self.spans: list[tuple[int, int, str]] = []
        self.job_x = 10**6

    def show(self, hints: Sequence[tuple[str, str]], right: Text) -> None:
        colors = ui.palette(self.app)
        text = Text(no_wrap=True)
        self.spans = []
        # 宽度不够时先舍弃靠后的提示，任务状态（进度与取消）始终保留。
        budget = self.size.width - right.cell_len - 4 if right.cell_len else 10**6
        for index, (key, action) in enumerate(hints):
            if index and text.cell_len + 3 + cell_len(key) + 1 + cell_len(action) > budget:
                break
            if index:
                text.append("   ")
            start = text.cell_len
            text.append(key, style=f"bold {colors.accent}")
            text.append(f" {action}", style=colors.muted)
            press = KEY_PRESS.get(key, key.split("/")[0])
            self.spans.append((start, text.cell_len, press))
        gap = self.size.width - text.cell_len - right.cell_len - 2
        self.job_x = 10**6
        if gap > 0:
            text.append(" " * gap)
            self.job_x = text.cell_len
            text.append_text(right)
        self.update(text)

    def on_click(self, event: events.Click) -> None:
        x = event.x - 1
        app: Any = self.app
        if x >= self.job_x:
            event.stop()
            if app.job_running:
                app.push_screen(
                    ConfirmPopup("后台任务", f"{app.job_status}\n取消这个任务？"),
                    lambda ok: ok and app.cancel_workflow(),
                )
            return
        for start, end, key in self.spans:
            if start <= x < end:
                event.stop()
                app.simulate_key(key)
                return


class StackFrame(Static):
    """叠放的书页：每一层页面是一张带边框的纸，上层页面依次向右下错开压在下面，只露出
    标题边与左边线；当前页在最前，标题边上写页名与副标题。

    整个外框由四个停靠的部件拼成（top / left / right / bottom），内容区不再另画边框。
    点击露出的标题边或左边线直接翻回那一页。
    """

    def __init__(self, part: str, **kwargs: Any) -> None:
        super().__init__("", classes="frame", **kwargs)
        self.part = part
        self.hover: int | None = None

    def pages(self) -> list[Any]:
        stack = [screen for screen in self.app.screen_stack if isinstance(screen, Chrome)]
        return stack[: stack.index(self.screen) + 1] if self.screen in stack else [self.screen]

    def _color(self, index: int, colors: ui.Palette) -> str:
        return colors.accent if index == self.hover else colors.line

    def redraw(self) -> None:
        pages = self.pages()
        depth = len(pages)
        colors = ui.palette(self.app)
        # 停靠部件互相重叠，靠外边距让出位置：左右两条边线夹在标题边与底边之间。
        if self.part == "top":
            self.styles.height = depth
        elif self.part in ("left", "right"):
            self.styles.margin = (depth, 0, 2, 0)
            if self.part == "left":
                self.styles.width = depth
        width = max(self.screen.size.width, 10)
        text = Text(no_wrap=True)
        if self.part == "top":
            for row, page in enumerate(pages):
                if row:
                    text.append("\n")
                for column in range(row):
                    text.append("│", style=self._color(column, colors))
                color = self._color(row, colors)
                text.append("╭─ ", style=color)
                current = row == depth - 1
                if current:
                    title = self.screen.heading()
                else:
                    title = Text(
                        page.page_title(),
                        style=colors.accent if row == self.hover else colors.muted,
                    )
                room = width - row - 5
                title.truncate(max(room, 1), overflow="ellipsis")
                text.append_text(title)
                text.append(" " + "─" * max(room - title.cell_len, 0), style=color)
                text.append("╮", style=color)
        elif self.part == "left":
            rows = max(self.size.height, 1)
            line = Text(no_wrap=True)
            for column in range(depth):
                line.append("│", style=self._color(column, colors))
            text = Text("\n").join([line] * rows)
        elif self.part == "right":
            text = Text("\n".join(["│"] * max(self.size.height, 1)), style=colors.line)
        else:
            text.append("╰", style=self._color(0, colors))
            for column in range(1, depth):
                text.append("┴", style=self._color(column, colors))
            text.append("─" * max(width - depth - 1, 0) + "╯", style=colors.line)
        self.update(text)

    def _index(self, event: events.MouseEvent) -> int | None:
        depth = len(self.pages())
        if self.part == "top":
            index = min(event.y, event.x) if event.x < event.y else event.y
        elif self.part in ("left", "bottom"):
            index = event.x
        else:
            return None
        # 当前页（最后一层）不必翻。
        return index if 0 <= index < depth - 1 else None

    def _set_hover(self, index: int | None) -> None:
        if index != self.hover:
            for part in self.screen.query(StackFrame):
                part.hover = index
                part.redraw()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self._set_hover(self._index(event))

    def on_leave(self, _event: events.Leave) -> None:
        self._set_hover(None)

    def on_click(self, event: events.Click) -> None:
        index = self._index(event)
        if index is None:
            return
        event.stop()
        target = self.pages()[index]
        while self.app.screen is not target and len(self.app.screen_stack) > 2:
            self.app.pop_screen()


class Chrome:
    """所有全屏页面共用的外壳：叠放的书页外框与底部提示栏。"""

    PATH = "首页"
    PAGE_ICON = "open"
    TITLE = ""
    HINTS: ClassVar[Sequence[tuple[str, str]]] = NAV_HINTS

    def page_title(self) -> str:
        return str(getattr(self, "TITLE", "")) or "·"

    def subtitle(self) -> str:
        return ""

    def heading(self) -> Text:
        """当前页写在书页标题边上的文字：粗体页名 + 弱化的副标题。"""
        app: Any = self.app  # type: ignore[attr-defined]
        colors = ui.palette(app)
        text = Text(
            label(self.PAGE_ICON, self.page_title(), app.nerd_font), style=f"bold {colors.fg}"
        )
        subtitle = self.subtitle()
        if subtitle:
            text.append("  " + subtitle, style=colors.muted)
        return text

    def chrome_top(self) -> ComposeResult:
        for part in ("top", "left", "right", "bottom"):
            yield StackFrame(part, id=f"frame-{part}")
        yield KeyBar(id="status")

    def chrome_bottom(self) -> ComposeResult:
        yield from ()

    def _update_status(self) -> None:
        app: Any = self.app  # type: ignore[attr-defined]
        colors = ui.palette(app)
        busy = app.job_running
        right = Text(no_wrap=True)
        if busy or app.job_status != "空闲":
            right.append("● " + str(app.job_status), style=colors.warn if busy else colors.muted)
        if busy and app.job_progress is not None:
            _stage, done, total, _ = app.job_progress
            right.append("  ")
            if total:
                right.append_text(ui.bar(done / total, 16, colors.warn, colors.surface))
                right.append(" ")
            right.append(app.progress_text(), style=colors.fg)
            right.append("  点击取消", style=colors.muted)
        hints = list(self.HINTS) + [("?", "帮助")]
        if not app.key_hints:
            hints = [("?", "帮助")]
        self.query_one("#status", KeyBar).show(hints, right)  # type: ignore[attr-defined]
        for part in self.query(StackFrame):  # type: ignore[attr-defined]
            part.redraw()


class ShellScreen(Chrome, Screen):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,left,h", "back", "返回"),
        ("j,down", "down", "下移"),
        ("k,up", "up", "上移"),
        ("g", "first", "首项"),
        ("shift+g", "last", "末项"),
        ("l,right", "open", "进入下一层"),
        ("enter,space", "activate", "打开 / 复核"),
        ("slash", "search", "搜索"),
    ]

    def on_mouse_down(self, event: events.MouseDown) -> None:
        start_drag(self, event)

    def shell(self, content: list[object]) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            yield from content  # type: ignore[misc]
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
        self.refresh_chrome()
        for view in self.query(ListView):
            view.focus()
            break

    def refresh_chrome(self) -> None:
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

    def action_activate(self) -> None:
        """回车：默认与 → 相同（进入下一层）；可复核的页面改为复核。"""
        self.action_open()

    @on(NavigationListView.Activated)
    def activated(self, event: NavigationListView.Activated) -> None:
        if event.keyboard:
            self.action_activate()
        else:
            self.open_index(event.index)


class SortHeader(Static):
    """可点击的表头：点击某列按该列排序，再点切换升降序（与文件管理器一致）。"""

    def on_click(self, event: events.Click) -> None:
        screen = self.screen
        if isinstance(screen, TableScreen):
            column = ui.column_at(screen.COLUMNS, screen.row_width(), event.x - 2)
            if column is not None:
                event.stop()
                screen.sort_by(column)


class TableScreen(ShellScreen):
    """带表头的单列表页：子类声明列与每行单元格，基类负责对齐、排序和保持选中位置。

    子类实现 sort_key(row, 列号) 返回可比较的值即可让该列可排序（None 表示不可排序）。
    """

    COLUMNS: ClassVar[Sequence[ui.Column]] = ()
    DEFAULT_SORT: ClassVar[tuple[int, bool] | None] = None
    EMPTY = "暂无数据"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("s", "cycle_sort", "切换排序列 / 升降序"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Any] = []
        self.sort = self.DEFAULT_SORT

    def table(self) -> list[object]:
        return [SortHeader("", classes="thead"), NavigationListView(id="items")]

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

    def sort_key(self, row: Any, column: int) -> Any:
        return None

    def sortable(self, column: int) -> bool:
        return bool(self.rows) and self.sort_key(self.rows[0], column) is not None

    def sort_by(self, column: int) -> None:
        if not self.sortable(column):
            return
        if self.sort is not None and self.sort[0] == column:
            self.sort = (column, not self.sort[1])
        else:
            self.sort = (column, False)
        self.reload()

    def action_cycle_sort(self) -> None:
        """s：当前列升序 → 降序 → 下一可排序列。"""
        columns = [i for i in range(len(self.COLUMNS)) if self.sortable(i)]
        if not columns:
            return
        if self.sort is None or self.sort[0] not in columns:
            self.sort = (columns[0], False)
        elif not self.sort[1]:
            self.sort = (self.sort[0], True)
        else:
            self.sort = (columns[(columns.index(self.sort[0]) + 1) % len(columns)], False)
        self.reload()

    def ordered(self, rows: list[Any]) -> list[Any]:
        if self.sort is None:
            return rows
        column, descending = self.sort
        keyed = [(self.sort_key(row, column), row) for row in rows]
        present = [pair for pair in keyed if pair[0] is not None]
        missing = [row for key, row in keyed if key is None]
        present.sort(key=lambda pair: pair[0], reverse=descending)
        return [row for _, row in present] + missing

    def row_width(self) -> int:
        view = self.query_one("#items", ListView)
        if view.size.width:
            return max(view.size.width - 4, 40)
        depth = len(self.query_one("#frame-left", StackFrame).pages())
        return max(self.app.size.width - 6 - depth, 40)

    def reload(self) -> None:
        colors = ui.palette(self.app)
        width = self.row_width()
        view = self.query_one("#items", ListView)
        previous = view.index or 0
        self.rows = self.ordered(self.items())
        self.query_one(".thead", Static).update(
            ui.table_header(self.COLUMNS, width, colors.muted, self.sort, colors.accent)
        )
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


class HomeScreen(ShellScreen):
    """首页仪表盘：顶部四张编号卡片即入口（比赛、待复核、账号、设置），下面是最近比赛与
    待复核队列。

    卡片可点击或按 1–4 进入；两个列表用 Tab 切换，回车 / 双击直接打开比赛或证据。
    """

    PAGE_ICON = "home"
    TITLE = "ojaudit"
    PATH = "首页"
    HINTS = (
        ("↵", "打开"),
        ("tab", "切换面板"),
        ("1-4", "卡片"),
        ("c", "采集"),
        ("d", "剔除比赛"),
        ("q", "退出"),
    )
    TILES = (
        ("list", "比赛", "contests"),
        ("pending", "待复核", "pending"),
        ("login", "账号", "account"),
        ("settings", "设置", "settings"),
    )
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("1", "tile(0)", "比赛列表"),
        ("2,p", "tile(1)", "待复核"),
        ("3", "tile(2)", "账户与登录"),
        ("4", "tile(3)", "设置"),
        ("c", "collect", "采集新比赛"),
        ("o", "open_id", "打开比赛 ID"),
        ("d", "toggle_excluded", "剔除所选比赛"),
    ]
    QUEUE_LIMIT = 50

    def __init__(self) -> None:
        super().__init__()
        self.recent: list[Any] = []
        self.summaries: dict[tuple[str, str], ContestSummary] = {}
        self.queue: list[Any] = []
        self.people: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def page_title(self) -> str:
        return "首页"

    def heading(self) -> Text:
        colors = ui.palette(self.app)
        text = Text(label("home", "ojaudit", self.app.nerd_font), style=f"bold {colors.accent}")
        text.append("  训练赛代码审查工作台", style=colors.fg)
        text.append("  ·  检测结果只是复核线索，不等于违规认定", style=colors.muted)
        return text

    def compose(self) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            yield Horizontal(
                *(Static("", id=f"tile-{i}", classes="tile") for i in range(len(self.TILES))),
                id="tiles",
            )
            with Vertical(id="home-recent", classes="panel"):
                yield Static("", classes="thead", id="recent-head")
                yield NavigationListView(id="recent")
            with Vertical(id="home-queue", classes="panel"):
                yield NavigationListView(id="queue")

    def on_mount(self) -> None:
        for index, (icon, name, _target) in enumerate(self.TILES):
            mark = glyph(icon, self.app.nerd_font)
            self.query_one(
                f"#tile-{index}"
            ).border_title = f"[{index + 1}] {mark + ' ' if mark else ''}{name}"
        self.query_one("#home-recent").border_title = "最近比赛"
        self.query_one("#home-queue").border_title = "待复核"
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

    def _tile(self, index: int, value: Text, caption: str) -> None:
        colors = ui.palette(self.app)
        body = Text(no_wrap=True, overflow="ellipsis")
        body.append_text(value)
        body.append("\n" + caption, style=colors.muted)
        self.query_one(f"#tile-{index}", Static).update(body)

    def refresh_home(self) -> None:
        from ojaudit.tui.account_service import current_uid, logged_in_locally
        from ojaudit.tui.workflow import pending_entries

        colors = ui.palette(self.app)
        # 被过滤规则或手动剔除的比赛不在首页出现，也不进待复核。
        contests = self.app.contests.list_contests()
        pending = pending_entries(self.app.contests) if contests else []
        findings = [entry for entry in pending if entry.kind == "finding"]
        suspects = len(pending) - len(findings)
        logged_in = logged_in_locally()
        self.summaries = {
            (e.contest.platform, e.contest.contest_id): contest_summary(
                self.app.contests, e.contest
            )
            for e in contests
        }
        states = Counter(summary.state for summary in self.summaries.values())

        def number(value: int, unit: str, color: str) -> Text:
            text = Text(str(value), style=f"bold {color if value else colors.fg}")
            text.append(" " + unit, style=colors.fg)
            return text

        self._tile(
            0,
            number(len(contests), "场", colors.accent),
            f"已分析 {states['已分析']} · 未采集 {states['未采集']}"
            if contests
            else "登录后按 S 同步",
        )
        self._tile(1, number(len(findings), "条线索", colors.warn), f"存疑选手 {suspects} 名")
        uid = current_uid()
        self._tile(
            2,
            Text("已登录", style=f"bold {colors.ok}")
            if logged_in
            else Text("未登录", style=f"bold {colors.muted}"),
            (f"UID {uid}" if uid else "牛客") if logged_in else "按 3 扫码登录",
        )
        db = self.app.contests.db_path
        try:
            shown = "~/" + str(db.relative_to(db.home()))
        except ValueError:
            shown = str(db)
        self._tile(
            3,
            Text(f"主题 {self.app.theme_name}", style=f"bold {colors.fg}"),
            shown if db.is_file() else "数据库尚未创建",
        )

        self.recent = contests
        columns = (
            ui.Column("比赛"),
            ui.Column("日期", 10),
            ui.Column("状态", 8),
            ui.Column("实锤 强 疑", 10),
            ui.Column("复核", 12),
        )
        view = self.query_one("#recent", ListView)
        total = max(view.size.width - 4, 50)
        self.query_one("#recent-head", Static).update(ui.table_header(columns, total, colors.muted))
        rows = []
        for entry in contests:
            summary = self.summaries[(entry.contest.platform, entry.contest.contest_id)]
            rows.append(
                ui.table_row(
                    [
                        Text(entry.contest.name, style=colors.fg),
                        Text(summary.date, style=colors.muted),
                        state_text(summary, colors),
                        level_counts(summary, colors),
                        ui.progress(summary.reviewed, summary.findings, colors, 4),
                    ],
                    columns,
                    total,
                )
            )
        _fill(view, rows, Text("还没有比赛：登录后进入比赛列表按 S 同步", style=colors.muted))

        self.queue = pending[: self.QUEUE_LIMIT]
        self.people = {}
        queue = self.query_one("#queue", ListView)
        self.query_one("#home-queue").border_subtitle = (
            f"共 {len(pending)} 项 · p 查看全部" if pending else ""
        )
        _fill(
            queue,
            [self._queue_row(entry, queue.size.width - 4) for entry in self.queue],
            Text("没有待复核的内容", style=colors.ok),
        )

    def _queue_row(self, entry: Any, width: int) -> Text:
        from ojaudit.tui.review_data import ReviewData

        colors = ui.palette(self.app)
        key = (entry.contest.platform, entry.contest.contest_id)
        if key not in self.people:
            self.people[key] = {
                str(p["uid"]): p for p in ReviewData(self.app.contests, entry.contest).people()
            }
        people = self.people[key]

        def person(uid: str) -> Text:
            row = people.get(uid, {"name": uid, "mark": "", "hidden": False})
            return ui.person_text(
                str(row["name"]), uid, str(row["mark"]), bool(row["hidden"]), colors, False
            )

        columns = (ui.Column("", 8), ui.Column("", 3), ui.Column(""), ui.Column("", 18))
        if entry.kind == "finding":
            item = entry.finding or {}
            pair = person(str(item["uid_a"]))
            pair.append("  ↔  ", style=colors.muted)
            pair.append_text(person(str(item["uid_b"])))
            cells = [
                ui.chip(ui.level_name(item["verdict_level"]), colors.level(item["verdict_level"])),
                Text(ui.problem_label(item["problem_index"]), style=f"bold {colors.fg}"),
                pair,
                Text(entry.contest.name, style=colors.muted),
            ]
        else:
            cells = [
                ui.dot("存疑", colors.caution),
                Text("—", style=colors.muted),
                person(entry.uid),
                Text(entry.contest.name, style=colors.muted),
            ]
        return ui.table_row(cells, columns, max(width, 40))

    def open_index(self, index: int) -> None:
        focused = self.app.focused
        view_id = focused.id if isinstance(focused, ListView) else "recent"
        if view_id == "recent":
            if not self.recent:
                self.app.push_screen(ContestListScreen(self.app.contests))
            elif 0 <= index < len(self.recent):
                contest = self.recent[index].contest
                open_contest(
                    self.app, contest, self.summaries.get((contest.platform, contest.contest_id))
                )
            return
        if view_id == "queue" and 0 <= index < len(self.queue):
            self.open_queue(self.queue[index])

    def action_tile(self, index: int) -> None:
        target = self.TILES[index][2]
        if target == "contests":
            self.app.push_screen(ContestListScreen(self.app.contests))
        elif target == "pending":
            self.action_pending()
        elif target == "account":
            from ojaudit.tui.account_screen import AccountScreen

            self.app.push_screen(AccountScreen())
        else:
            from ojaudit.tui.settings_model import SettingsModel
            from ojaudit.tui.settings_screen import SettingsScreen

            self.app.push_screen(SettingsScreen(SettingsModel(db_path=self.app.contests.db_path)))

    def on_click(self, event: events.Click) -> None:
        widget = event.widget
        while widget is not None and widget is not self:
            if widget.has_class("tile"):
                event.stop()
                self.action_tile(int(str(widget.id).removeprefix("tile-")))
                return
            widget = widget.parent  # type: ignore[assignment]

    def open_queue(self, entry: Any) -> None:
        from ojaudit.tui.review_data import ReviewData
        from ojaudit.tui.review_screens import EvidenceScreen, PersonScreen

        data = ReviewData(self.app.contests, entry.contest)
        if entry.kind == "finding":
            sequence = [
                item.finding
                for item in self.queue
                if item.kind == "finding" and item.contest == entry.contest
            ]
            self.app.push_screen(EvidenceScreen(data, "首页", entry.finding, sequence=sequence))
        else:
            self.app.push_screen(PersonScreen(data, "首页", entry.uid))

    def action_toggle_excluded(self) -> None:
        view = self.query_one("#recent", ListView)
        index = view.index if view.index is not None else -1
        if 0 <= index < len(self.recent):
            toggle_excluded(self, self.recent[index].contest)

    def action_pending(self) -> None:
        from ojaudit.tui.pending_screen import PendingScreen

        self.app.push_screen(PendingScreen())

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


def _fill(view: ListView, rows: Sequence[Text], empty: Text) -> None:
    """重填列表并保持选中位置；没有数据时显示一行说明。"""
    previous = view.index or 0
    view.clear()
    for row in rows or [empty]:
        view.append(ListItem(Label(row)))
    view.call_after_refresh(setattr, view, "index", max(0, min(previous, len(rows) - 1)))


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
    PAGE_ICON = "list"
    TITLE = "比赛列表"
    PATH = "首页 › 比赛列表"
    HINTS = (
        ("↵", "打开"),
        ("c", "采集"),
        ("R", "重新分析"),
        ("S", "同步"),
        ("d", "剔除/恢复"),
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
        ("d", "toggle_excluded", "剔除 / 恢复所选比赛"),
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

    def action_toggle_excluded(self) -> None:
        view = self.query_one("#items", ListView)
        row = self.selected_row(view.index if view.index is not None else -1)
        if row is not None:
            toggle_excluded(self, row.contest)

    def open_index(self, index: int) -> None:
        row = self.selected_row(index)
        if row is None:
            return
        summary = self.summaries.get((row.contest.platform, row.contest.contest_id))
        open_contest(self.app, row.contest, summary)


def toggle_excluded(screen: Any, contest: Contest) -> None:
    """像设管理者一样一键剔除比赛（不用写正则）；再按一次恢复。"""
    try:
        removed = screen.app.contests.toggle_excluded(contest)
    except (OSError, TypeError, ValueError) as exc:
        screen.notify(f"保存失败：{exc}", severity="error")
        return
    if removed:
        screen.notify(f"已剔除「{contest.name}」：不再显示、不进待复核（比赛列表按 a 可找回）")
    else:
        screen.notify(f"已恢复「{contest.name}」")
    if isinstance(screen, HomeScreen):
        screen.refresh_home()
    else:
        screen.reload()


def open_contest(app: Any, contest: Contest, summary: ContestSummary | None) -> None:
    """打开比赛总览；还没采集的比赛先询问是否采集并检测。"""
    if summary is not None and summary.state == "未采集":
        app.push_screen(
            ConfirmPopup(
                "采集比赛", f"「{contest.name}」还没有采集。\n现在采集并检测？", default=True
            ),
            lambda ok: (
                ok and app.start_workflow(contest.contest_id, "collect_analyze", contest.platform)
            ),
        )
        return
    app.push_screen(ContestOverviewScreen(contest, app.contests))


class ContestOverviewScreen(ShellScreen):
    PAGE_ICON = "contest"
    TITLE = "比赛总览"
    HINTS = (("↵", "打开"), ("←", "返回"), ("c", "重新采集"), ("R", "重新分析"))
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
            f"{stats.participants} 人 · {summary.flagged} 人涉及线索",
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

    PAGE_ICON = "contest"
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
