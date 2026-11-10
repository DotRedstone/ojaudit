"""
Module: TUI / pending screen
Description: 跨比赛列出待复核线索和存疑人员并返回原比赛详情。
Scope: TUI
Notes: 只读取本地分析与人工标记，不执行网络请求。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.widgets import Static

from ojaudit.tui import ui
from ojaudit.tui.review_data import ReviewData, pair_key, pair_scores
from ojaudit.tui.review_screens import EvidenceScreen, PersonScreen, level_chip, status_text
from ojaudit.tui.screens import TableScreen
from ojaudit.tui.workflow import PendingEntry, is_pending, review_entries


class PendingScreen(TableScreen):
    """跨比赛的复核面板：待处理 / 已处理 / 全部；默认按人物对总嫌疑度排序。"""

    TITLE = "复核"
    PATH = "首页 › 待复核"
    HINTS = (("↵", "打开"), ("f", "面板"), ("s", "排序"), ("/", "搜索"), ("esc", "返回"))
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *TableScreen.BINDINGS,
        ("f", "cycle_filter", "切换 待处理 / 已处理 / 全部"),
    ]
    FILTERS = ("待处理", "已处理", "全部")
    COLUMNS = (
        ui.Column("等级", 8),
        ui.Column("比赛"),
        ui.Column("题", 3),
        ui.Column("选手 A"),
        ui.Column("选手 B"),
        ui.Column("嫌疑度", 9, "right"),
        ui.Column("复核", 14),
    )
    DEFAULT_SORT = (5, True)
    EMPTY = "这里没有需要处理的内容"

    def __init__(self) -> None:
        super().__init__()
        self.filter_index = 0
        self._all: list[PendingEntry] = []
        self._people: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._pairs: dict[tuple[str, str, str, str], tuple[int, int]] = {}
        self.tab_spans: list[tuple[int, int]] = []

    @property
    def entries(self) -> list[PendingEntry]:
        return self.rows

    def table(self) -> list[object]:
        return [Static("", id="filters"), *super().table()]

    def subtitle(self) -> str:
        return "跨比赛 · 同一对选手的线索排在一起 · 嫌疑度 = 实锤 3 / 中偏强 2 / 存疑 1 之和"

    def _filtered(self, mode: str) -> list[PendingEntry]:
        if mode == "待处理":
            return [entry for entry in self._all if is_pending(entry)]
        if mode == "已处理":
            return [entry for entry in self._all if not is_pending(entry)]
        return list(self._all)

    def items(self) -> list[PendingEntry]:
        self._all = review_entries(self.app.contests)
        self._people = {}
        self._pairs = {}
        contests = {(e.contest.platform, e.contest.contest_id): e.contest for e in self._all}
        for key, contest in contests.items():
            data = ReviewData(self.app.contests, contest)
            for person in data.people():
                self._people[(*key, str(person["uid"]))] = person
            for pair, value in pair_scores(data.findings()).items():
                self._pairs[(*key, *pair)] = value
        return self._filtered(self.FILTERS[self.filter_index])

    def reload(self) -> None:
        super().reload()
        colors = ui.palette(self.app)
        tabs = Text()
        self.tab_spans = []
        for index, mode in enumerate(self.FILTERS):
            start = tabs.cell_len
            label_text = f" {mode} {len(self._filtered(mode))} "
            if index == self.filter_index:
                tabs.append(label_text, style=f"bold {colors.bg} on {colors.accent}")
            else:
                tabs.append(label_text, style=colors.muted)
            self.tab_spans.append((start, tabs.cell_len))
            tabs.append(" ")
        self.query_one("#filters", Static).update(tabs)

    def action_cycle_filter(self) -> None:
        self.filter_index = (self.filter_index + 1) % len(self.FILTERS)
        self.reload()

    def on_click(self, event: events.Click) -> None:
        if event.widget is not None and event.widget.id == "filters":
            for index, (start, end) in enumerate(self.tab_spans):
                if start <= event.x - 1 < end:
                    self.filter_index = index
                    self.reload()
                    return

    def _contest_key(self, entry: PendingEntry) -> tuple[str, str]:
        return entry.contest.platform, entry.contest.contest_id

    def _pair(self, entry: PendingEntry) -> tuple[str, str, str, str]:
        if entry.kind != "finding":
            return (*self._contest_key(entry), entry.uid, "")
        return (*self._contest_key(entry), *pair_key(entry.finding or {}))

    def _person(self, entry: PendingEntry, uid: str) -> Text:
        person = self._people.get((*self._contest_key(entry), uid), {})
        return ui.person_text(
            str(person.get("name", uid)),
            uid,
            str(person.get("mark", "")),
            bool(person.get("hidden")),
            ui.palette(self.app),
            False,
        )

    def sort_key(self, row: Any, column: int) -> Any:
        entry: PendingEntry = row
        item = entry.finding or {}
        pair = self._pair(entry)
        score = self._pairs.get(pair, (0, 0))[0] if entry.kind == "finding" else 0
        return {
            0: -ui.level_rank(item.get("verdict_level", "")) if item else -9,
            1: (entry.contest.name, entry.contest.contest_id),
            2: int(item.get("problem_index", -1)),
            3: str(self._person(entry, str(item.get("uid_a", entry.uid))).plain),
            4: str(self._person(entry, str(item.get("uid_b", ""))).plain),
            5: (score, ui.Reversed(pair)),
            6: str(item.get("status", "存疑人员")),
        }.get(column)

    def cells(self, row: Any) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        entry: PendingEntry = row
        contest = Text(entry.contest.name, style=colors.fg)
        if entry.kind == "finding":
            item = entry.finding or {}
            score, count = self._pairs.get(self._pair(entry), (0, 0))
            suspicion = Text(str(score), style=f"bold {colors.danger}" if score >= 5 else colors.fg)
            suspicion.append(f" ·{count}题", style=colors.muted)
            return [
                level_chip(item.get("verdict_level", ""), colors),
                contest,
                Text(ui.problem_label(item.get("problem_index", 0)), style=f"bold {colors.fg}"),
                self._person(entry, str(item.get("uid_a"))),
                self._person(entry, str(item.get("uid_b"))),
                suspicion,
                status_text(str(item.get("status", "")), colors),
            ]
        return [
            ui.dot("存疑", colors.caution),
            contest,
            Text("—", style=colors.muted),
            self._person(entry, entry.uid),
            Text(""),
            Text("—", style=colors.muted),
            Text("待定性", style=colors.caution),
        ]

    def on_workflow_finished(self) -> None:
        self.reload()

    def open_index(self, index: int) -> None:
        entry = self.selected_row(index)
        if entry is None:
            return
        data = ReviewData(self.app.contests, entry.contest)
        path = f"首页 › 待复核 › {entry.contest.name}"
        if entry.kind == "finding":
            assert entry.finding is not None
            # 证据页翻页沿用本列表中同一比赛的顺序。
            sequence = [
                item.finding
                for item in self.rows
                if item.kind == "finding"
                and item.finding is not None
                and self._contest_key(item) == self._contest_key(entry)
            ]
            self.app.push_screen(EvidenceScreen(data, path, entry.finding, sequence=sequence))
        else:
            self.app.push_screen(PersonScreen(data, path, entry.uid))
