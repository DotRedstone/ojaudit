"""
Module: TUI / ranking screen
Description: 展示本地推导榜单：名单处理策略、表格内容选项、预览与导出（导出后复制路径）。
Scope: TUI
Notes: 预览与导出使用同一张表格；预览明确注明非官方，不将人工标记直接当作作弊事实。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, ClassVar

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ListView, Static

from ojaudit.core.ranking import RankingOptions
from ojaudit.core.ranking_table import TableOptions
from ojaudit.tui import ui
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView, refill
from ojaudit.tui.ranking_data import export_ranking, final_ranking, pending_warnings, ranking_table
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.screens import ShellScreen
from ojaudit.tui.splitter import Splitter

# 名单处理：哪些人出现在榜单上、是否标注。
POLICIES = (
    ("作弊者", ("除名", "标记"), ("drop", "mark")),
    ("存疑者", ("照常", "标记", "剔除"), ("keep", "mark", "drop")),
    ("管理者", ("剔除", "标记"), ("drop", "mark")),
    ("未提交者", ("保留", "剔除"), ("keep", "drop")),
)
# 表格内容：榜单展示哪些列，以及导出格式。
TABLE = (
    ("各题得分", ("隐藏", "显示"), (False, True)),
    ("提交次数", ("隐藏", "显示"), (False, True)),
    ("时间", ("隐藏", "显示"), (False, True)),
    ("导出格式", ("Excel", "Markdown", "CSV", "HTML"), ("xlsx", "md", "csv", "html")),
)
GROUPS = {"ranking-options": POLICIES, "ranking-table": TABLE}
_WIDTHS = {
    "名次": (4, "right"),
    "UID": (12, "left"),
    "总分": (6, "right"),
    "提交": (4, "right"),
    "最后得分": (8, "left"),
    "标记": (6, "left"),
}


def copy_to_clipboard(app: Any, text: str) -> None:
    """复制到系统剪贴板：优先用 wl-copy / xclip / xsel / pbcopy，同时发 OSC 52（远程终端也可用）。"""
    tools = (
        (["wl-copy"], bool(os.environ.get("WAYLAND_DISPLAY"))),
        (["xclip", "-selection", "clipboard"], bool(os.environ.get("DISPLAY"))),
        (["xsel", "--clipboard", "--input"], bool(os.environ.get("DISPLAY"))),
        (["pbcopy"], True),
    )
    for command, usable in tools:
        if usable and shutil.which(command[0]):
            try:
                subprocess.run(command, input=text.encode(), timeout=2, check=False)
                break
            except (OSError, subprocess.SubprocessError):
                continue
    app.copy_to_clipboard(text)


class RankingScreen(ShellScreen):
    PAGE_ICON = "ranking"
    TITLE = "排行榜"
    HINTS = (
        ("↵", "切换取值"),
        ("tab", "切换面板"),
        ("a", "设为/取消管理者"),
        ("e", "导出并复制路径"),
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
        ("tab", "focus_next", "切换 名单处理 / 表格内容 / 预览"),
        ("shift+tab", "focus_previous", "反向切换面板"),
        ("e", "export", "导出并复制路径"),
        ("a", "toggle_manager", "把预览中选中的人设为 / 取消管理者"),
    ]
    PANELS = ("ranking-options", "ranking-table", "ranking-preview")

    def __init__(self, data: ReviewData) -> None:
        super().__init__()
        self.data = data
        self.contest = data.contest
        self.choice_indices = [0] * len(POLICIES)
        self.table_indices = [0] * len(TABLE)
        self.preview_rows: list[dict[str, Any]] = []
        self.PATH = f"首页 › 比赛列表 › {data.contest.name} › 排行榜"

    def subtitle(self) -> str:
        return "本地提交推算 · 非官方排名"

    def compose(self) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"), Horizontal(id="ranking-columns"):
            with Vertical(id="ranking-side"):
                for view_id, items in GROUPS.items():
                    yield NavigateListView(
                        *(ListItem(Label(name)) for name, _, _ in items),
                        id=view_id,
                        classes="panel ranking-group",
                    )
                yield Static("", id="ranking-warning", classes="panel")
            yield Splitter("ranking-side", "ranking", minimum=30)
            with Vertical(id="ranking-main", classes="panel"):
                yield Static("", classes="thead")
                yield NavigateListView(id="ranking-preview")
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
        self.query_one("#ranking-options").border_title = "名单处理"
        self.query_one("#ranking-table").border_title = "表格内容"
        self.query_one("#ranking-warning").border_title = "提醒"
        self.query_one("#ranking-main").border_title = "预览"
        self.refresh_ranking()
        super().on_mount()
        self.query_one("#ranking-options", ListView).focus()

    def on_layout_change(self) -> None:
        self.refresh_ranking()

    def policy(self) -> RankingOptions:
        return RankingOptions(
            **{
                field: POLICIES[index][2][self.choice_indices[index]]
                for index, field in enumerate(("cheaters", "suspects", "managers", "inactive"))
            }
        )

    def table_options(self) -> TableOptions:
        return TableOptions(
            **{
                field: TABLE[index][2][self.table_indices[index]]
                for index, field in enumerate(("per_problem", "attempts", "times"))
            }
        )

    def format_name(self) -> str:
        return str(TABLE[-1][2][self.table_indices[-1]])

    def _indices(self, view_id: str) -> list[int]:
        return self.choice_indices if view_id == "ranking-options" else self.table_indices

    def refresh_ranking(self) -> None:
        colors = ui.palette(self.app)
        for view_id, items in GROUPS.items():
            view = self.query_one(f"#{view_id}", ListView)
            width = max(view.size.width - 4, 24)
            for item, (name, titles, _), choice in zip(
                view.children, items, self._indices(view_id)
            ):
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

        # 预览与导出用同一张表：列随「表格内容」变化，没有任何标记时不显示标记列。
        policy = self.policy()
        self.preview_rows = list(final_ranking(self.data, policy).rows)
        table = ranking_table(self.data, policy, self.table_options())
        columns = []
        for header, kind in zip(table.headers, table.kinds):
            if header == "姓名":
                columns.append(ui.Column(header))
                continue
            if "用时" in header:
                width, align = 8, "left"
            else:
                width, align = _WIDTHS.get(header, (max(cell_len(header), 5), "right"))
            columns.append(ui.Column(header, width, "right" if kind != "text" else align))
        preview = self.query_one("#ranking-preview", ListView)
        total = max(self.query_one("#ranking-main").size.width - 6, 30)
        self.query_one("#ranking-main .thead", Static).update(
            ui.table_header(columns, total, colors.muted)
        )
        lines = []
        for cells, mark in zip(table.rows, table.marks):
            styled: list[Text] = []
            for header, value in zip(table.headers, cells):
                if header == "姓名":
                    styled.append(Text(str(value), style=colors.person(mark, mark == "manager")))
                elif header == "标记":
                    color = colors.muted if mark == "manager" else colors.mark(mark)
                    styled.append(Text(str(value), style=color))
                elif header in ("名次", "UID") or "用时" in header or "提交" in header:
                    styled.append(Text(str(value), style=colors.muted))
                else:
                    styled.append(Text(str(value), style=colors.fg))
            lines.append(ui.table_row(styled, columns, total))
        refill(preview, lines or [Text("当前策略下无可展示人员", style=colors.muted)])
        self.query_one(
            "#ranking-main"
        ).border_subtitle = f"{len(table.rows)} 人 · {len(table.headers)} 列 · {TABLE[-1][1][self.table_indices[-1]]}"
        self.refresh_chrome()

    def change(self, delta: int) -> None:
        view = self.active_view()
        if view.id not in GROUPS:
            return
        index = view.index or 0
        indices = self._indices(str(view.id))
        choices = GROUPS[str(view.id)][index][1]
        indices[index] = (indices[index] + delta) % len(choices)
        self.refresh_ranking()

    def action_previous(self) -> None:
        self.change(-1)

    def action_next(self) -> None:
        self.change(1)

    def active_view(self) -> ListView:
        view = self.app.focused
        if isinstance(view, ListView) and view.id in self.PANELS:
            return view
        return self.query_one("#ranking-options", ListView)

    def _cycle(self, step: int) -> None:
        current = self.PANELS.index(str(self.active_view().id))
        target = self.PANELS[(current + step) % len(self.PANELS)]
        self.query_one(f"#{target}", ListView).focus()

    def action_focus_next(self) -> None:
        self._cycle(1)

    def action_focus_previous(self) -> None:
        self._cycle(-1)

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
            destination = export_ranking(
                self.data, self.policy(), self.format_name(), table=self.table_options()
            )
        except (OSError, ValueError) as exc:
            self.notify(f"导出失败：{exc}", severity="error")
            return
        copy_to_clipboard(self.app, str(destination))
        self.notify(f"已导出，路径已复制：{destination}")

    def open_index(self, index: int) -> None:
        self.action_next()

    def action_back(self) -> None:
        self.app.pop_screen()
