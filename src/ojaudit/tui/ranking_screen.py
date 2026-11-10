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
from textual.screen import Screen
from textual.widgets import Footer, Label, ListView, Static

from ojaudit.core.ranking import RankingOptions
from ojaudit.tui.interaction import Breadcrumb
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.ranking_data import export_ranking, final_ranking, pending_warnings
from ojaudit.tui.review_data import ReviewData

POLICIES = (
    ("作弊者", ("剔除", "标记"), ("drop", "mark")),
    ("存疑者", ("照常", "标记", "剔除"), ("keep", "mark", "drop")),
    ("管理者", ("剔除", "标记"), ("drop", "mark")),
    ("格式", ("Markdown", "CSV", "HTML"), ("md", "csv", "html")),
)


class RankingScreen(Screen):
    TITLE = "排行榜 · 本地推导（非官方）"
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
    CSS = """
    #ranking-options { height: 7; border: round $panel; }
    #ranking-preview { height: 1fr; border: round $panel; }
    #ranking-warning { height: 3; padding: 0 1; color: $warning; }
    """

    def __init__(self, data: ReviewData) -> None:
        super().__init__()
        self.data = data
        self.choice_indices = [0, 0, 0, 0]

    def compose(self) -> ComposeResult:
        yield Breadcrumb(f"首页 › 比赛列表 › {self.data.contest.name} › 排行榜", id="breadcrumb")
        with Vertical(id="pane"):
            yield Static("本地提交成绩推导，非官方排名", id="ranking-note")
            yield ListView(id="ranking-options")
            yield Static("", id="ranking-warning")
            yield ListView(id="ranking-preview")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#pane", Vertical).border_title = self.TITLE
        self.query_one("#ranking-options", ListView).border_title = "导出策略"
        self.query_one("#ranking-preview", ListView).border_title = "预览"
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
            view.append(ListItem(Label(f"{label}   ‹ {titles[self.choice_indices[index]]} ›")))
        view.call_after_refresh(setattr, view, "index", selected)
        warnings = pending_warnings(self.data)
        self.query_one("#ranking-warning", Static).update(
            "提示：" + ("；".join(warnings) if warnings else "暂无待处理项") + "（不阻止导出）"
        )
        preview = self.query_one("#ranking-preview", ListView)
        preview.clear()
        for row in final_ranking(self.data, self.policy()).rows:
            mark = {"manager": "管理", "suspect": "存疑", "cheater": "作弊者"}.get(
                row.get("person_mark", ""), ""
            )
            preview.append(
                ListItem(
                    Label(
                        f"#{row['rank']}  {row['name']} · {row['score']:g} 分"
                        f"{' · ' + mark if mark else ''}"
                    )
                )
            )
        if not preview.children:
            preview.append(ListItem(Label("当前策略下无可展示人员")))
        self.query_one("#status", Static).update(" NORMAL  ›  排行榜 · 非官方推导   │  e 导出")

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

    def action_back(self) -> None:
        self.app.pop_screen()
