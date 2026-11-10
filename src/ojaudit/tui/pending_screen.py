"""跨比赛待复核入口：线索与存疑人员均回到原比赛的详情页面。"""

from __future__ import annotations

from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.review_screens import EvidenceScreen, PersonScreen
from ojaudit.tui.screens import ShellScreen
from ojaudit.tui.workflow import PendingEntry, pending_entries


class PendingScreen(ShellScreen):
    TITLE = "待复核 · 跨比赛"
    PATH = "首页 › 待复核"

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[PendingEntry] = []

    def compose(self):
        from textual.widgets import ListView

        yield from self.shell([ListView(id="pending-items")])

    def on_mount(self) -> None:
        self.reload()
        super().on_mount()

    def on_screen_resume(self) -> None:
        self.reload()

    def on_workflow_finished(self) -> None:
        self.reload()

    def reload(self) -> None:
        from textual.widgets import Label, ListItem, ListView

        self.entries = pending_entries(self.app.contests)
        view = self.query_one("#pending-items", ListView)
        view.clear()
        for entry in self.entries:
            prefix = f"{entry.contest.name} [{entry.contest.contest_id}]"
            if entry.kind == "finding":
                item = entry.finding
                assert item is not None
                title = (
                    f"{prefix} · 待复核 · 题 {item['problem_index']} "
                    f"· {item['uid_a']} ↔ {item['uid_b']}"
                )
            else:
                title = f"{prefix} · 存疑人员 · {entry.uid}"
            view.append(ListItem(Label(title)))
        if not self.entries:
            view.append(ListItem(Label("暂无跨比赛待复核项")))
        view.call_after_refresh(setattr, view, "index", 0)

    def open_index(self, index: int) -> None:
        if not 0 <= index < len(self.entries):
            return
        entry = self.entries[index]
        data = ReviewData(self.app.contests, entry.contest)
        path = f"首页 › 待复核 › {entry.contest.name}"
        if entry.kind == "finding":
            assert entry.finding is not None
            self.app.push_screen(EvidenceScreen(data, path, entry.finding))
        else:
            self.app.push_screen(PersonScreen(data, path, entry.uid))
