"""
Module: TUI / review screens
Description: 提供证据复核、人员和题目浏览及提交代码导航页面。
Scope: TUI
Notes:
- 人工修改只经 ReviewData 调用核心 Store 的标记/复核接口。
- 历史失效线索只展示，不支持对过期分析结果写入结论。
"""

from __future__ import annotations

from difflib import unified_diff
from typing import Any, ClassVar

from rich.syntax import Syntax
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListView, Select, Static

from ojaudit.core.reviews import REVIEW_STATUSES
from ojaudit.tui import palette
from ojaudit.tui.icons import breadcrumb, label
from ojaudit.tui.interaction import Breadcrumb
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView as NavigationListView
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.screens import ShellScreen


def _syntax(code: str, language: str) -> Syntax:
    syntax = {"cpp": "cpp", "python": "python", "java": "java"}.get(language, "text")
    return Syntax(code or "", syntax, line_numbers=True, word_wrap=False)


class ChoiceDialog(ModalScreen[tuple[str, str] | None]):
    """保存人员标记或线索结论及备注。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "取消", priority=True),
        Binding("h", "back", "取消"),
    ]


    def __init__(
        self, title: str, options: tuple[tuple[str, str], ...], value: str = "", note: str = ""
    ) -> None:
        super().__init__()
        self.heading = title
        self.options = options
        self.value = value
        self.note = note

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="dialog-box"):
            yield Label(label("mark", self.heading, self.app.nerd_font))
            yield Select(
                [(label, key) for label, key in self.options],
                value=self.value if self.value else self.options[0][1],
                allow_blank=False,
                id="choice",
            )
            yield Input(value=self.note, placeholder="备注（可选）", id="note")
            with Horizontal():
                yield Button(
                    label("save", "保存", self.app.nerd_font), id="save", variant="primary"
                )
                yield Button(label("cancel", "取消", self.app.nerd_font), id="cancel")

    @on(Input.Submitted)
    def submit_note(self, event: Input.Submitted) -> None:
        self.action_save()

    def action_save(self) -> None:
        value = self.query_one("#choice", Select).value
        if isinstance(value, str):
            self.dismiss((value, self.query_one("#note", Input).value))

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            value = self.query_one("#choice", Select).value
            if isinstance(value, str):
                self.dismiss((value, self.query_one("#note", Input).value))

    def action_back(self) -> None:
        choice = self.query_one("#choice", Select)
        if choice.expanded:
            choice.expanded = False
            choice.focus()
        else:
            self.dismiss(None)


MARK_CHOICES = (("正常", "normal"), ("存疑", "suspect"), ("作弊者", "cheater"))
REVIEW_CHOICES = tuple((status, status) for status in REVIEW_STATUSES)


class ReviewListScreen(ShellScreen):
    """复用导航、面包屑和动态列表。"""

    TITLE = "列表"

    def __init__(self, data: ReviewData, path: str) -> None:
        super().__init__()
        self.data = data
        self.PATH = path
        self.rows: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield from self.shell([NavigationListView(id="items")])

    def on_mount(self) -> None:
        self.reload()
        super().on_mount()

    def on_screen_resume(self) -> None:
        self.reload()

    def items(self) -> list[dict[str, Any]]:
        return []

    def label_for(self, row: dict[str, Any]) -> str:
        return str(row)

    def icon_for(self, row: dict[str, Any]) -> str:
        if row.get("hidden"):
            return "manager"
        return {"cheater": "cheater", "suspect": "suspect", "normal": "normal"}.get(
            row.get("mark"), "list"
        )

    def reload(self) -> None:
        view = self.query_one("#items", ListView)
        previous = view.index or 0
        self.rows = self.items()
        view.clear()
        for item in self.rows:
            widget = ListItem(
                Label(label(self.icon_for(item), self.label_for(item), self.app.nerd_font))
            )
            if item.get("hidden"):
                widget.styles.color = palette.MANAGER
            elif item.get("mark") == "cheater":
                widget.styles.color = palette.CONFIRMED
            elif item.get("mark") == "suspect":
                widget.styles.color = palette.SUSPECT
            elif item.get("mark") == "normal":
                widget.styles.color = palette.NORMAL
            view.append(widget)
        if not self.rows:
            view.append(ListItem(Label(label("list", "暂无数据", self.app.nerd_font))))
        view.call_after_refresh(setattr, view, "index", min(previous, len(self.rows) - 1))

    def selected_row(self, index: int) -> dict[str, Any] | None:
        return self.rows[index] if 0 <= index < len(self.rows) else None


class FindingsScreen(ReviewListScreen):
    TITLE = "线索 · 当前与已失效"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("f", "cycle_filter", "切换线索过滤"),
    ]
    FILTERS = ("全部", "高优先级", "未处理", "已处理")

    def __init__(self, data: ReviewData, path: str) -> None:
        super().__init__(data, path)
        self.filter_index = 0

    def items(self) -> list[dict[str, Any]]:
        rows = self.data.findings()
        mode = self.FILTERS[self.filter_index]
        if mode == "高优先级":
            return [
                row
                for row in rows
                if not row["is_stale"] and str(row["verdict_level"]).lower() == "high"
            ]
        if mode == "未处理":
            return [row for row in rows if not row["is_stale"] and row["status"] == "待复核"]
        if mode == "已处理":
            return [row for row in rows if not row["is_stale"] and row["status"] != "待复核"]
        return rows

    def action_cycle_filter(self) -> None:
        self.filter_index = (self.filter_index + 1) % len(self.FILTERS)
        self.reload()
        self.query_one("#pane", Vertical).border_subtitle = self.FILTERS[self.filter_index]
        self.notify(f"线索筛选：{self.FILTERS[self.filter_index]}")

    def icon_for(self, row: dict[str, Any]) -> str:
        return "warning" if row["is_stale"] else "findings"

    def label_for(self, row: dict[str, Any]) -> str:
        flag = " · 已失效" if row["is_stale"] else ""
        return (
            f"题 {row['problem_index']} · {row['uid_a']} ↔ {row['uid_b']} "
            f"· {row['verdict_level']} · {row['status']}{flag}"
        )

    def open_index(self, index: int) -> None:
        item = self.selected_row(index)
        if item is not None:
            self.app.push_screen(EvidenceScreen(self.data, self.PATH, item))


class EvidenceScreen(ShellScreen):
    TITLE = "线索证据"
    HINTS = "Tab 差异  r 复核  m 标记  j/k 下一条  Esc 返回"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,h,left", "back", "返回"),
        ("tab", "diff", "差异视图"),
        ("shift+tab", "diff", "差异视图"),
        ("j,down", "next", "下一条"),
        ("k,up", "previous", "上一条"),
        ("right,l,enter,space", "diff", "差异视图"),
        ("g", "first_evidence", "首条"),
        ("shift+g", "last_evidence", "末条"),
        ("r", "review", "复核"),
        ("m", "mark", "人员标记"),
        ("u", "switch_person", "切换选手"),
        ("n", "next", "下一条"),
        ("p", "previous", "上一条"),
    ]

    def __init__(self, data: ReviewData, parent_path: str, finding: dict[str, Any]) -> None:
        super().__init__()
        self.data = data
        self.parent_path = parent_path
        self.finding = finding
        self.diff_mode = False
        self.person_side = 0
        self._sync_path()

    def _sync_path(self) -> None:
        self.PATH = f"{self.parent_path} › 证据 · 题 {self.finding['problem_index']}"
        self.CURRENT = f"{self.finding['uid_a']} ↔ {self.finding['uid_b']}"

    def compose(self) -> ComposeResult:
        yield from self.shell(
            [
                Static("", id="evidence-meta"),
                Horizontal(
                    Static("", id="code-left", classes="source-pane"),
                    Static("", id="code-right", classes="source-pane"),
                    id="code-pair",
                ),
            ]
        )

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#pane", Vertical).border_title = label(
            "evidence", self.TITLE, self.app.nerd_font
        )
        self.render_evidence()
        self._update_status()

    def render_evidence(self) -> None:
        finding = self.finding
        reason = finding["reasons"]
        scores = finding["scores"]

        def score_label(key: str, value: object) -> str:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
                filled = round(float(value) * 10)
                return f"{key}: {'█' * filled}{'░' * (10 - filled)} {value}"
            return f"{key}: {value}"

        score_text = (
            " · ".join(score_label(k, v) for k, v in scores.items())
            if isinstance(scores, dict)
            else str(scores)
        )
        reason_text = "；".join(str(x) for x in reason) if isinstance(reason, list) else str(reason)
        stale = "【已失效】" if finding["is_stale"] else ""
        self.query_one("#evidence-meta", Static).update(
            label(
                "evidence",
                f"{stale}分级：{finding['verdict_level']} · 复核：{finding['status']}\n"
                f"插件评分：{score_text or '无'}\n理由 / 时间线：{reason_text or '无'}",
                self.app.nerd_font,
            )
        )
        left = self.data.representative(
            finding["uid_a"], int(finding["problem_index"]), finding["language"]
        )
        right = self.data.representative(
            finding["uid_b"], int(finding["problem_index"]), finding["language"]
        )
        left_code = left["code"] if left else "（本地无对应提交）"
        right_code = right["code"] if right else "（本地无对应提交）"
        left_view = self.query_one("#code-left", Static)
        right_view = self.query_one("#code-right", Static)
        if self.diff_mode:
            diff = "".join(
                unified_diff(
                    left_code.splitlines(keepends=True),
                    right_code.splitlines(keepends=True),
                    fromfile=str(finding["uid_a"]),
                    tofile=str(finding["uid_b"]),
                )
            )
            left_view.update(Syntax(diff or "（无文本差异）", "diff", line_numbers=True))
            right_view.update("Tab：返回代码对照")
        else:
            left_view.update(_syntax(left_code, finding["language"]))
            right_view.update(_syntax(right_code, finding["language"]))
        color = {
            "high": palette.CONFIRMED,
            "medium": palette.STRONG,
            "low": palette.SUSPECT,
        }.get(str(finding["verdict_level"]).lower(), palette.EXCLUDED)
        self.query_one("#evidence-meta", Static).styles.border_left = ("solid", color)
        self.refresh_breadcrumb()
        self._update_status()

    def action_first_evidence(self) -> None:
        self._move(-1000000)

    def action_last_evidence(self) -> None:
        self._move(1000000)

    def action_diff(self) -> None:
        self.diff_mode = not self.diff_mode
        self.render_evidence()

    def action_switch_person(self) -> None:
        self.person_side = 1 - self.person_side
        self.notify(f"当前标记对象：{self.target_uid}")

    @property
    def target_uid(self) -> str:
        return str(self.finding["uid_b" if self.person_side else "uid_a"])

    def action_mark(self) -> None:
        uid = self.target_uid
        person = self.data.person(uid)
        if person["hidden"]:
            self.notify("管理者不可标记为参赛选手", severity="warning")
            return
        self.app.push_screen(
            ChoiceDialog(
                f"标记 {person['name']} ({uid})", MARK_CHOICES, person["mark"], person["note"]
            ),
            lambda result: self._save_mark(uid, result),
        )

    def _save_mark(self, uid: str, result: tuple[str, str] | None) -> None:
        if result is not None:
            self.data.mark(uid, *result)
            self.notify("人员标记已保存")

    def action_review(self) -> None:
        if self.finding["is_stale"]:
            self.notify("已失效线索仅供查看", severity="warning")
            return
        self.app.push_screen(
            ChoiceDialog(
                "线索复核",
                REVIEW_CHOICES,
                (self.finding["status"] if self.finding["status"] in REVIEW_STATUSES else ""),
                self.finding.get("note", ""),
            ),
            self._save_review,
        )

    def _save_review(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        self.data.review(self.finding, *result)
        self._refresh_current()
        # 处理完后定位下一条待复核线索。
        findings = self.data.findings()
        current = next(
            (index for index, item in enumerate(findings) if self._same(item, self.finding)), -1
        )
        waiting = [
            item
            for item in findings[current + 1 :] + findings[: max(current, 0)]
            if not item["is_stale"] and item["status"] == "待复核"
        ]
        if waiting:
            self.finding = waiting[0]
            self._sync_path()
            self.render_evidence()
        else:
            self.notify("当前没有更多待复核线索")

    @staticmethod
    def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
        return all(
            a[key] == b[key] for key in ("run_id", "uid_a", "uid_b", "problem_index", "language")
        )

    def _refresh_current(self) -> None:
        for item in self.data.findings():
            if self._same(item, self.finding):
                self.finding = item
                self.render_evidence()
                break

    def _move(self, delta: int) -> None:
        findings = self.data.findings()
        current = next((i for i, item in enumerate(findings) if self._same(item, self.finding)), 0)
        if findings:
            target = (current + delta) % len(findings)
            if delta == -1000000:
                target = 0
            elif delta == 1000000:
                target = len(findings) - 1
            self.finding = findings[target]
            self._sync_path()
            self.render_evidence()

    def action_next(self) -> None:
        self._move(1)

    def action_previous(self) -> None:
        self._move(-1)


class PeopleScreen(ReviewListScreen):
    TITLE = "选手"

    def items(self) -> list[dict[str, Any]]:
        return self.data.people()

    def icon_for(self, row: dict[str, Any]) -> str:
        return (
            "manager"
            if row["hidden"]
            else {"cheater": "cheater", "suspect": "suspect", "normal": "normal"}.get(
                row["mark"], "person"
            )
        )

    def label_for(self, row: dict[str, Any]) -> str:
        marks = {"normal": "正常", "suspect": "存疑", "cheater": "作弊者"}
        suffix = (
            " · 管理"
            if row["hidden"]
            else (f" · {marks[row['mark']]}" if row["mark"] in marks else "")
        )
        return f"{row['name']} [{row['uid']}]{suffix}"

    def open_index(self, index: int) -> None:
        person = self.selected_row(index)
        if person:
            self.app.push_screen(PersonScreen(self.data, self.PATH, person["uid"]))


class PersonScreen(ReviewListScreen):
    TITLE = "选手详情"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("m", "mark", "人员标记"),
    ]

    def __init__(self, data: ReviewData, path: str, uid: str) -> None:
        super().__init__(data, f"{path} › {data.person(uid)['name']}")
        self.uid = uid
        self.CURRENT = uid

    def icon_for(self, row: dict[str, Any]) -> str:
        return "problem"

    def items(self) -> list[dict[str, Any]]:
        indexes = {row["problem_index"] for row in self.data.submissions(self.uid)}
        return [item for item in self.data.problems() if item["problem_index"] in indexes]

    def label_for(self, row: dict[str, Any]) -> str:
        return f"题 {row['problem_index']} · {row['title']}"

    def open_index(self, index: int) -> None:
        item = self.selected_row(index)
        if item:
            self.app.push_screen(
                SubmissionScreen(self.data, self.PATH, self.uid, int(item["problem_index"]))
            )

    def action_mark(self) -> None:
        person = self.data.person(self.uid)
        if person["hidden"]:
            self.notify("管理者不可标记为参赛选手", severity="warning")
            return
        self.app.push_screen(
            ChoiceDialog(f"标记 {person['name']}", MARK_CHOICES, person["mark"], person["note"]),
            self._save,
        )

    def _save(self, result: tuple[str, str] | None) -> None:
        if result is not None:
            self.data.mark(self.uid, *result)
            self.notify("人员标记已保存")


class SubmissionScreen(ReviewListScreen):
    TITLE = "提交历史（含 WA / CE）"

    def __init__(self, data: ReviewData, path: str, uid: str, problem: int) -> None:
        super().__init__(data, f"{path} › 题 {problem} › 提交")
        self.uid = uid
        self.problem = problem

    def icon_for(self, row: dict[str, Any]) -> str:
        return "submissions"

    def items(self) -> list[dict[str, Any]]:
        return self.data.submissions(self.uid, self.problem)

    def label_for(self, row: dict[str, Any]) -> str:
        return (
            f"{row['submission_id']} · {row['verdict']} · {row['language']} "
            f"· {row['submit_time']} · {row['phase']}"
        )

    def open_index(self, index: int) -> None:
        if self.selected_row(index):
            self.app.push_screen(CodeScreen(self.data, self.PATH, self.rows, index))


class ProblemsScreen(ReviewListScreen):
    TITLE = "题目"

    def icon_for(self, row: dict[str, Any]) -> str:
        return "problem"

    def items(self) -> list[dict[str, Any]]:
        return self.data.problems()

    def label_for(self, row: dict[str, Any]) -> str:
        return f"题 {row['problem_index']} · {row['title']}"

    def open_index(self, index: int) -> None:
        item = self.selected_row(index)
        if item:
            self.app.push_screen(
                ProblemScreen(self.data, self.PATH, int(item["problem_index"]), item["title"])
            )


class ProblemScreen(ReviewListScreen):
    TITLE = "题目代表代码 · s 切换排序"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("s", "sort", "切换排序"),
    ]
    ORDERS = ("time", "name", "findings")

    def __init__(self, data: ReviewData, path: str, problem: int, name: str) -> None:
        super().__init__(data, f"{path} › {name}")
        self.problem = problem
        self.order = "time"

    def icon_for(self, row: dict[str, Any]) -> str:
        return "manager" if row.get("hidden") else "code"

    def items(self) -> list[dict[str, Any]]:
        return self.data.representatives(self.problem, self.order)

    def label_for(self, row: dict[str, Any]) -> str:
        manager = " · 管理" if row.get("hidden") else ""
        return (
            f"{row['name']} · {row['verdict']} · {row['language']} · {row['submit_time']}{manager}"
        )

    def action_sort(self) -> None:
        self.order = self.ORDERS[(self.ORDERS.index(self.order) + 1) % len(self.ORDERS)]
        self.reload()
        self.notify({"time": "AC 时间", "name": "姓名", "findings": "线索数"}[self.order])

    def open_index(self, index: int) -> None:
        if self.selected_row(index):
            self.app.push_screen(CodeScreen(self.data, self.PATH, self.rows, index))


class CodeScreen(ShellScreen):
    TITLE = "代码浏览"
    HINTS = "j/k 上下份  m 标记  [ ] 历史  Esc 返回"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,h,left", "back", "返回"),
        ("n,j,down,right,l,enter,space", "next", "下一份"),
        ("p,k,up", "previous", "上一份"),
        ("g", "first_code", "首份"),
        ("shift+g", "last_code", "末份"),
        ("left_square_bracket", "earlier", "上次提交"),
        ("right_square_bracket", "later", "下次提交"),
        ("m", "mark", "人员标记"),
    ]

    def __init__(
        self, data: ReviewData, path: str, items: list[dict[str, Any]], index: int = 0
    ) -> None:
        super().__init__()
        self.data = data
        self.items = items
        self.index = index
        self.base_path = path

    def compose(self) -> ComposeResult:
        yield from self.shell([Static("", id="code-meta"), Static("", id="code-body")])

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#pane", Vertical).border_title = label(
            "code", self.TITLE, self.app.nerd_font
        )
        self.render_code()

    @property
    def current(self) -> dict[str, Any]:
        return self.items[self.index]

    def render_code(self) -> None:
        row = self.current
        self.PATH = f"{self.base_path} › 代码 {row['submission_id']}"
        self.CURRENT = str(row["uid"])
        person = self.data.person(row["uid"])
        labels = {"normal": "正常", "suspect": "存疑", "cheater": "作弊者"}
        mark = "管理" if person["hidden"] else labels.get(person["mark"], "未标记")
        self.query_one("#breadcrumb", Static).update(breadcrumb(self.PATH, self.app.nerd_font))
        self.query_one("#code-meta", Static).update(
            label(
                "code",
                f"{person['name']} · 题 {row['problem_index']} · {row['verdict']} "
                f"· {row['language']} · {mark} · 提交 {self.index + 1}/{len(self.items)}",
                self.app.nerd_font,
            )
        )
        self.query_one("#code-body", Static).update(_syntax(row["code"], row["language"]))
        self._update_status()

    def action_first_code(self) -> None:
        self.index = 0
        self.render_code()

    def action_last_code(self) -> None:
        self.index = len(self.items) - 1
        self.render_code()

    def action_next(self) -> None:
        if self.index + 1 < len(self.items):
            self.index += 1
            self.render_code()

    def action_previous(self) -> None:
        if self.index > 0:
            self.index -= 1
            self.render_code()

    def _history(self, delta: int) -> None:
        row = self.current
        history = self.data.submissions(row["uid"], int(row["problem_index"]))
        current = next(
            (i for i, item in enumerate(history) if item["submission_id"] == row["submission_id"]),
            -1,
        )
        target = current + delta
        if current >= 0 and 0 <= target < len(history):
            selected = history[target]
            existing = next(
                (
                    i
                    for i, item in enumerate(self.items)
                    if item["submission_id"] == selected["submission_id"]
                    and item["uid"] == selected["uid"]
                ),
                None,
            )
            if existing is None:
                self.items = history
                self.index = target
            else:
                self.index = existing
            self.render_code()

    def action_earlier(self) -> None:
        self._history(-1)

    def action_later(self) -> None:
        self._history(1)

    def action_mark(self) -> None:
        uid = self.current["uid"]
        person = self.data.person(uid)
        if person["hidden"]:
            self.notify("管理者不可标记为参赛选手", severity="warning")
            return
        self.app.push_screen(
            ChoiceDialog(f"标记 {person['name']}", MARK_CHOICES, person["mark"], person["note"]),
            lambda result: self._save(uid, result),
        )

    def _save(self, uid: str, result: tuple[str, str] | None) -> None:
        if result is not None:
            self.data.mark(uid, *result)
            self.render_code()
