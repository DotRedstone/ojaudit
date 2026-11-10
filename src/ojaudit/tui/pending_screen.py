"""
Module: TUI / pending screen
Description: 跨比赛列出待复核线索和存疑人员并返回原比赛详情。
Scope: TUI
Notes: 只读取本地分析与人工标记，不执行网络请求。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rich.text import Text

from ojaudit.tui import ui
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.review_screens import EvidenceScreen, PersonScreen, level_chip
from ojaudit.tui.screens import TableScreen
from ojaudit.tui.workflow import PendingEntry, pending_entries


class PendingScreen(TableScreen):
    TITLE = "待复核"
    PATH = "首页 › 待复核"
    HINTS = (("↵", "打开"), ("/", "搜索"), ("esc", "返回"))
    COLUMNS = (
        ui.Column("类型", 8),
        ui.Column("比赛"),
        ui.Column("内容"),
    )
    EMPTY = "所有比赛都已处理完毕"

    def __init__(self) -> None:
        super().__init__()
        self._people_names: dict[tuple[str, str, str], str] = {}

    @property
    def entries(self) -> list[PendingEntry]:
        return self.rows

    def subtitle(self) -> str:
        return f"跨比赛 · {len(self.rows)} 项未处理线索与存疑选手"

    def items(self) -> list[PendingEntry]:
        entries = pending_entries(self.app.contests)
        self._people_names = {}
        contests = {(e.contest.platform, e.contest.contest_id): e.contest for e in entries}
        for contest in contests.values():
            for person in ReviewData(self.app.contests, contest).people():
                self._people_names[(contest.platform, contest.contest_id, person["uid"])] = person[
                    "name"
                ]
        return entries

    def _person_name(self, entry: PendingEntry, uid: str) -> str:
        return self._people_names.get((entry.contest.platform, entry.contest.contest_id, uid), uid)

    def cells(self, row: Any) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        entry: PendingEntry = row
        contest = Text(entry.contest.name, style=colors.fg)
        contest.append(f" {entry.contest.contest_id}", style=colors.muted)
        if entry.kind == "finding":
            item = entry.finding or {}
            body = Text(f"题 {item.get('problem_index')}  ", style=colors.muted)
            body.append(self._person_name(entry, str(item.get("uid_a"))), style=colors.fg)
            body.append(" ⇄ ", style=colors.muted)
            body.append(self._person_name(entry, str(item.get("uid_b"))), style=colors.fg)
            return [level_chip(item.get("verdict_level", ""), colors), contest, body]
        return [
            ui.dot("存疑", colors.caution),
            contest,
            Text(f"{self._person_name(entry, entry.uid)} {entry.uid}", style=colors.fg),
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
            self.app.push_screen(EvidenceScreen(data, path, entry.finding))
        else:
            self.app.push_screen(PersonScreen(data, path, entry.uid))
