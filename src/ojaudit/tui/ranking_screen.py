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
from textual.widgets import Label, ListItem, ListView, Static

from ojaudit.core.ranking import RankingOptions
from ojaudit.tui.icons import breadcrumb
from ojaudit.tui.icons import label as label_icon
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
        ("escape", "back", "返回"),
        ("h", "previous", "前一选项"),
        ("l", "next", "后一选项"),
        ("enter", "next", "切换选项"),
        ("e", "export", "导出"),
        ("j", "down", "向下"),
        ("k", "up", "向上"),
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
        yield Static(
            breadcrumb(f"首页 › 比赛列表 › {self.data.contest.name} › 排行榜", self.app.nerd_font),
            id="breadcrumb",
        )
        with Vertical(id="pane"):
            yield Static(
                label_icon("ranking", "本地提交成绩推导，非官方排名", self.app.nerd_font),
                id="ranking-note",
            )
            yield ListView(id="ranking-options")
            yield Static("", id="ranking-warning")
            yield ListView(id="ranking-preview")
        yield Static("", id="status")

    def on_mount(self) -> None:
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
                ListItem(
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
                ListItem(
                    Label(
                        label_icon(
                            "ranking",
                            f"#{row['rank']}  {row['name']} · {row['score']:g} 分"
                            f"{' · ' + mark if mark else ''}",
                            self.app.nerd_font,
                        )
                    )
                )
            )
        if not preview.children:
            preview.append(
                ListItem(Label(label_icon("people", "当前策略下无可展示人员", self.app.nerd_font)))
            )
        self.query_one("#status", Static).update(
            label_icon("ranking", " NORMAL  ›  排行榜 · 非官方推导   │  e 导出", self.app.nerd_font)
        )

    def change(self, delta: int) -> None:
        view = self.query_one("#ranking-options", ListView)
        index = view.index or 0
        choices = POLICIES[index][1]
        self.choice_indices[index] = (self.choice_indices[index] + delta) % len(choices)
        self.refresh_ranking()

    def action_previous(self) -> None:
        self.change(-1)

    def action_next(self) -> None:
        self.change(1)

    def action_down(self) -> None:
        view = self.query_one("#ranking-options", ListView)
        view.index = min((view.index or 0) + 1, len(POLICIES) - 1)

    def action_up(self) -> None:
        view = self.query_one("#ranking-options", ListView)
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
