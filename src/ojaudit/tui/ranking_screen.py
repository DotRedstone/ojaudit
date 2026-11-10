"""
Module: TUI / ranking screen
Description: 展示本地推导榜单、排名策略和导出选项。
Scope: TUI
Notes: 预览明确注明非官方，不将人工标记直接当作作弊事实。
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, ListView, Static

from ojaudit.core.ranking import RankingOptions
from ojaudit.tui.icons import label as label_icon
from ojaudit.tui.interaction import NavigateListView
from ojaudit.tui.screens import ShellScreen
from ojaudit.tui.ui_components import StatusRow
from ojaudit.tui.ranking_data import export_ranking, final_ranking, pending_warnings
from ojaudit.tui.review_data import ReviewData

POLICIES = (
    ("作弊者", ("剔除", "标记"), ("drop", "mark")),
    ("存疑者", ("照常", "标记", "剔除"), ("keep", "mark", "drop")),
    ("管理者", ("剔除", "标记"), ("drop", "mark")),
    ("格式", ("Markdown", "CSV", "HTML"), ("md", "csv", "html")),
)


class RankingScreen(ShellScreen):
    TITLE = "排行榜 · 本地推导（非官方）"
    HINTS = "Enter 切换策略  e 导出  Tab 面板  j/k 移动  Esc 返回"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,h,left", "back", "返回"),
        ("right,l,enter,space", "next", "切换策略"),
        ("shift+left", "previous", "前一选项"),
        ("j,down", "down", "向下"),
        ("k,up", "up", "向上"),
        ("g", "first", "首项"),
        ("shift+g", "last", "末项"),
        ("tab,shift+tab", "focus_next", "切换面板"),
        ("e", "export", "导出"),
    ]

    def __init__(self, data: ReviewData) -> None:
        super().__init__()
        self.data = data
        self.contest = data.contest
        self.PATH = f"首页 › 比赛列表 › {data.contest.name} › 排行榜"
        self.choice_indices = [0, 0, 0, 0]

    def compose(self) -> ComposeResult:
        yield from self.shell(
            [
                Static(
                    label_icon(
                        "ranking",
                        "无官方 submit-list 快照：本地提交成绩推算（非官方排名）",
                        self.app.nerd_font,
                    ),
                    id="ranking-note",
                ),
                NavigateListView(id="ranking-options"),
                Static("", id="ranking-warning"),
                NavigateListView(id="ranking-preview"),
            ]
        )

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#pane", Vertical).border_title = label_icon(
            "ranking", self.TITLE, self.app.nerd_font
        )
        self.query_one("#ranking-options", ListView).border_title = label_icon(
            "settings", "导出策略", self.app.nerd_font
        )
        self.query_one("#ranking-preview", ListView).border_title = label_icon(
            "ranking", "预览", self.app.nerd_font
        )
        self.refresh_ranking()
        self.query_one("#ranking-options", ListView).focus()

    def policy(self) -> RankingOptions:
        return RankingOptions(
            cheaters=POLICIES[0][2][self.choice_indices[0]],
            suspects=POLICIES[1][2][self.choice_indices[1]],
            managers=POLICIES[2][2][self.choice_indices[2]],
        )

    def format_name(self) -> str:
        return POLICIES[3][2][self.choice_indices[3]]

    def refresh_ranking(self) -> None:
        view = self.query_one("#ranking-options", ListView)
        selected = view.index or 0
        view.clear()
        for index, (label, titles, _) in enumerate(POLICIES):
            view.append(
                StatusRow(
                    Label(
                        label_icon(
                            ("cheater", "suspect", "manager", "export")[index],
                            f"{label}   ‹ {titles[self.choice_indices[index]]} ›",
                            self.app.nerd_font,
                        )
                    )
                )
            )
        view.call_after_refresh(setattr, view, "index", selected)
        warnings = pending_warnings(self.data)
        self.query_one("#ranking-warning", Static).update(
            label_icon(
                "warning",
                "提示：" + ("；".join(warnings) if warnings else "暂无待处理项") + "（不阻止导出）",
                self.app.nerd_font,
            )
        )
        preview = self.query_one("#ranking-preview", ListView)
        preview.clear()
        for row in final_ranking(self.data, self.policy()).rows:
            mark = {"manager": "管理", "suspect": "存疑", "cheater": "作弊者"}.get(
                row.get("person_mark", ""), ""
            )
            preview.append(
                StatusRow(
                    label_icon(
                        "ranking",
                        f"#{row['rank']}  {row['name']} · {row['score']:g} 分"
                        f"{' · ' + mark if mark else ''}",
                        self.app.nerd_font,
                    ),
                    kind=f"mark-{row['person_mark']}"
                    if row.get("person_mark") in {"cheater", "suspect", "normal", "manager"}
                    else "",
                )
            )
        if not preview.children:
            preview.append(StatusRow("当前策略下无可展示人员"))
        self.query_one("#status", Static).update(
            self.app.status_line("排行榜 · 非官方推导", str(self.data.contest.contest_id))
        )

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

    def action_export(self) -> None:
        try:
            destination = export_ranking(self.data, self.policy(), self.format_name())
        except (OSError, ValueError) as exc:
            self.notify(f"导出失败：{exc}", severity="error")
        else:
            self.notify(f"已导出：{destination}")

    def open_index(self, index: int) -> None:
        if self.active_view().id == "ranking-options":
            self.change(1)

    def action_back(self) -> None:
        self.app.pop_screen()
