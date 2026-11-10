"""
Module: TUI / ranking screen
Description: 展示本地推导榜单、排名策略和导出选项。
Scope: TUI
Notes: 预览明确注明非官方，不将人工标记直接当作作弊事实。
"""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ListView, Static

from ojaudit.core.ranking import RankingOptions
from ojaudit.tui import ui
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView
from ojaudit.tui.ranking_data import export_ranking, final_ranking, pending_warnings
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.screens import ShellScreen
from ojaudit.tui.splitter import Splitter

POLICIES = (
    ("作弊者", ("除名", "标记"), ("drop", "mark")),
    ("存疑者", ("照常", "标记", "剔除"), ("keep", "mark", "drop")),
    ("管理者", ("剔除", "标记"), ("drop", "mark")),
    ("未提交者", ("保留", "剔除"), ("keep", "drop")),
    ("导出格式", ("Excel", "Markdown", "CSV", "HTML"), ("xlsx", "md", "csv", "html")),
)
PREVIEW_COLUMNS = (
    ui.Column("名次", 4, "right"),
    ui.Column("姓名"),
    ui.Column("得分", 8, "right"),
    ui.Column("标记", 8),
)


class RankingScreen(ShellScreen):
    PAGE_ICON = "ranking"
    TITLE = "排行榜"
    HINTS = (
        ("↵", "切换取值"),
        ("tab", "策略/预览"),
        ("a", "设为/取消管理者"),
        ("e", "导出"),
        ("←", "返回"),
    )
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,h,left", "back", "返回"),
        ("enter,space,right,l", "next", "下一个取值"),
        ("shift+enter,backspace", "previous", "上一个取值"),
        ("j,down", "down", "下移"),
        ("k,up", "up", "上移"),
        ("g", "first", "首项"),
        ("shift+g", "last", "末项"),
        ("tab,shift+tab", "focus_next", "切换策略 / 预览"),
        ("e", "export", "导出"),
        ("a", "toggle_manager", "把预览中选中的人设为 / 取消管理者"),
    ]

    def __init__(self, data: ReviewData) -> None:
        super().__init__()
        self.data = data
        self.contest = data.contest
        self.choice_indices = [0] * len(POLICIES)
        self.PATH = f"首页 › 比赛列表 › {data.contest.name} › 排行榜"

    def subtitle(self) -> str:
        return "本地提交推算 · 非官方排名"

    def compose(self) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            yield Static("", id="heading")
            with Horizontal(id="ranking-columns"):
                with Vertical(id="ranking-side"):
                    yield NavigateListView(
                        *(ListItem(Label(name)) for name, _, _ in POLICIES),
                        id="ranking-options",
                        classes="panel",
                    )
                    yield Static("", id="ranking-warning", classes="panel")
                yield Splitter("ranking-side", "ranking", minimum=30)
                with Vertical(id="ranking-main", classes="panel"):
                    yield Static("", classes="thead")
                    yield NavigateListView(id="ranking-preview")
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
        self.query_one("#ranking-options").border_title = "导出策略"
        self.query_one("#ranking-warning").border_title = "提醒"
        self.query_one("#ranking-main").border_title = "预览"
        self.refresh_ranking()
        self.query_one("#ranking-options", ListView).focus()
        super().on_mount()
        self.query_one("#ranking-options", ListView).focus()

    def on_layout_change(self) -> None:
        self.refresh_ranking()

    def policy(self) -> RankingOptions:
        return RankingOptions(
            cheaters=POLICIES[0][2][self.choice_indices[0]],
            suspects=POLICIES[1][2][self.choice_indices[1]],
            managers=POLICIES[2][2][self.choice_indices[2]],
            inactive=POLICIES[3][2][self.choice_indices[3]],
        )

    def format_name(self) -> str:
        return POLICIES[-1][2][self.choice_indices[-1]]

    def refresh_ranking(self) -> None:
        colors = ui.palette(self.app)
        options = self.query_one("#ranking-options", ListView)
        width = max(options.size.width - 4, 24)
        for item, (name, titles, _), choice in zip(options.children, POLICIES, self.choice_indices):
            value = Text("‹ ", style=colors.muted)
            value.append(titles[choice], style=f"bold {colors.accent}")
            value.append(" ›", style=colors.muted)
            item.query_one(Label).update(
                ui.table_row([name, value], (ui.Column(""), ui.Column("", 14, "right")), width)
            )
        warnings = pending_warnings(self.data)
        note = Text()
        for index, message in enumerate(warnings or ("暂无待处理项",)):
            if index:
                note.append("\n")
            note.append("• " + message, style=colors.warn if warnings else colors.muted)
        note.append("\n不阻止导出", style=colors.muted)
        self.query_one("#ranking-warning", Static).update(note)

        preview = self.query_one("#ranking-preview", ListView)
        total = max(self.query_one("#ranking-main").size.width - 6, 30)
        self.query_one("#ranking-main .thead", Static).update(
            ui.table_header(PREVIEW_COLUMNS, total, colors.muted)
        )
        selected = preview.index or 0
        preview.clear()
        self.preview_rows = list(final_ranking(self.data, self.policy()).rows)
        for row in self.preview_rows:
            mark = row.get("person_mark", "")
            label_text = {"manager": "管理", "suspect": "存疑", "cheater": "作弊者"}.get(mark, "")
            color = {"manager": colors.muted}.get(mark, colors.mark(mark))
            preview.append(
                ListItem(
                    Label(
                        ui.table_row(
                            [
                                Text(str(row["rank"]), style=colors.muted),
                                Text(
                                    str(row["name"]),
                                    style=colors.person(mark, mark == "manager"),
                                ),
                                f"{row['score']:g}",
                                Text(label_text, style=color),
                            ],
                            PREVIEW_COLUMNS,
                            total,
                        )
                    )
                )
            )
        if not preview.children:
            preview.append(ListItem(Label(Text("当前策略下无可展示人员", style=colors.muted))))
        preview.call_after_refresh(
            setattr, preview, "index", min(selected, len(preview.children) - 1)
        )
        self.refresh_chrome()

    def change(self, delta: int) -> None:
        view = self.query_one("#ranking-options", ListView)
        index = view.index or 0
        choices = POLICIES[index][1]
        self.choice_indices[index] = (self.choice_indices[index] + delta) % len(choices)
        self.refresh_ranking()

    def action_previous(self) -> None:
        if self.active_view().id == "ranking-options":
            self.change(-1)

    def action_next(self) -> None:
        if self.active_view().id == "ranking-options":
            self.change(1)

    def active_view(self) -> ListView:
        view = self.app.focused
        if isinstance(view, ListView) and view.id == "ranking-preview":
            return view
        return self.query_one("#ranking-options", ListView)

    def action_focus_next(self) -> None:
        view = self.active_view()
        target = "#ranking-preview" if view.id == "ranking-options" else "#ranking-options"
        self.query_one(target, ListView).focus()

    def action_first(self) -> None:
        self.active_view().index = 0

    def action_last(self) -> None:
        view = self.active_view()
        view.index = max(0, len(view.children) - 1)

    def action_down(self) -> None:
        view = self.active_view()
        view.index = min((view.index or 0) + 1, len(view.children) - 1)

    def action_up(self) -> None:
        view = self.active_view()
        view.index = max((view.index or 0) - 1, 0)

    def action_toggle_manager(self) -> None:
        """在预览里选中自己或其他工作人员，一键加入管理者名单（再按一次取消）。"""
        preview = self.query_one("#ranking-preview", ListView)
        rows = getattr(self, "preview_rows", [])
        index = preview.index if preview.index is not None else -1
        if not 0 <= index < len(rows):
            self.notify("先在右侧预览中选中一个人", severity="warning")
            return
        row = rows[index]
        uid, name = str(row["uid"]), str(row["name"])
        manager = row.get("person_mark") != "manager"
        self.data.set_manager(uid, manager)
        self.refresh_ranking()
        if manager:
            hint = "，已从榜单剔除" if self.policy().managers == "drop" else ""
            self.notify(f"已把 {name} 设为管理者{hint}（管理者策略选「标记」可在预览中看到并取消）")
        else:
            self.notify(f"已把 {name} 移出管理者名单")

    def action_export(self) -> None:
        try:
            destination = export_ranking(self.data, self.policy(), self.format_name())
        except (OSError, ValueError) as exc:
            self.notify(f"导出失败：{exc}", severity="error")
        else:
            self.notify(f"已导出：{destination}")

    def open_index(self, index: int) -> None:
        self.action_next()

    def action_back(self) -> None:
        self.app.pop_screen()
