"""
Module: TUI / review screens
Description: 提供证据复核、人员和题目浏览及提交代码导航页面。
Scope: TUI
Notes:
- 人工修改只经 ReviewData 调用核心 Store 的标记/复核接口。
- 历史失效线索只展示，不支持对过期分析结果写入结论。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from difflib import SequenceMatcher, unified_diff
from typing import Any, ClassVar

from rich.syntax import Syntax
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static

from ojaudit.core.reviews import DEFAULT_REVIEW_STATUS, REVIEW_STATUSES
from ojaudit.tui import ui
from ojaudit.tui.icons import label
from ojaudit.tui.review_data import ReviewData
from ojaudit.tui.screens import Dialog, ShellScreen, TableScreen, dialog_buttons

LANGUAGES = {"cpp": "C++", "python": "Python", "java": "Java"}


def _syntax(code: str, language: str, background: str, highlight: set[int] | None = None) -> Syntax:
    lexer = {"cpp": "cpp", "python": "python", "java": "java"}.get(language, "text")
    return Syntax(
        code or "",
        lexer,
        theme="monokai",
        line_numbers=True,
        word_wrap=False,
        background_color=background,
        highlight_lines=highlight,
    )


def _diff_text(left: str, right: str, names: tuple[str, str], colors: ui.Palette) -> Text:
    lines = list(
        unified_diff(
            left.splitlines(), right.splitlines(), fromfile=names[0], tofile=names[1], lineterm=""
        )
    )
    if not lines:
        return Text("两份代码没有文本差异", style=colors.muted)
    text = Text()
    for line in lines:
        if line.startswith(("+++", "---")):
            style = f"bold {colors.fg}"
        elif line.startswith("@@"):
            style = colors.accent
        elif line.startswith("+"):
            style = colors.ok
        elif line.startswith("-"):
            style = colors.danger
        else:
            style = colors.muted
        text.append(line + "\n", style=style)
    return text


def _changed_lines(left: str, right: str) -> tuple[set[int], set[int]]:
    """两侧不在相同块中的行号（从 1 开始），用于对照视图高亮。"""
    a, b = left.splitlines(), right.splitlines()
    same_a: set[int] = set()
    same_b: set[int] = set()
    for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        same_a.update(range(block.a + 1, block.a + block.size + 1))
        same_b.update(range(block.b + 1, block.b + block.size + 1))
    return set(range(1, len(a) + 1)) - same_a, set(range(1, len(b) + 1)) - same_b


def status_text(status: str, colors: ui.Palette, stale: bool = False) -> Text:
    if stale:
        return ui.dot("已失效", colors.muted)
    color = {
        DEFAULT_REVIEW_STATUS: colors.warn,
        "需进一步核实": colors.caution,
        "已核查": colors.ok,
        "无需跟进": colors.muted,
    }.get(status, colors.fg)
    return ui.dot(status, color)


def mark_text(person: dict[str, Any], colors: ui.Palette) -> Text:
    if person.get("hidden"):
        return Text("管理者", style=colors.muted)
    mark = person.get("mark", "")
    if mark not in ui.MARK_NAMES:
        return Text("—", style=colors.muted)
    return ui.dot(ui.MARK_NAMES[mark], colors.mark(mark))


def level_chip(level: object, colors: ui.Palette) -> Text:
    return ui.chip(ui.level_name(level), colors.level(level))


class ChoiceDialog(Dialog):
    """保存人员标记或线索结论及备注。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "取消", priority=True),
        Binding("h", "back", "取消"),
    ]

    def __init__(
        self,
        title: str,
        options: tuple[tuple[str, str], ...],
        value: str = "",
        note: str = "",
        hint: str = "",
    ) -> None:
        super().__init__()
        self.heading = title
        self.options = options
        self.value = value
        self.note = note
        self.hint = hint

    def compose(self) -> ComposeResult:
        icons = self.app.nerd_font
        with Vertical(id="dialog", classes="dialog"):
            yield Label(label("mark", self.heading, icons), classes="dialog-title")
            if self.hint:
                yield Label(self.hint, classes="dialog-hint")
            yield Select(
                [(name, key) for name, key in self.options],
                value=self.value if self.value else self.options[0][1],
                allow_blank=False,
                id="choice",
            )
            yield Input(value=self.note, placeholder="备注（可选）", id="note")
            yield dialog_buttons(("save", "保存"), ("cancel", "取消"), icons)

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
            self.action_save()

    def action_back(self) -> None:
        choice = self.query_one("#choice", Select)
        if choice.expanded:
            choice.expanded = False
            choice.focus()
        else:
            self.dismiss(None)


MARK_CHOICES = (("正常", "normal"), ("存疑", "suspect"), ("作弊者", "cheater"))
REVIEW_CHOICES = tuple((status, status) for status in REVIEW_STATUSES)


class ReviewListScreen(TableScreen):
    """比赛内的表格页：共享 ReviewData 和名字查找。"""

    TITLE = "列表"

    def __init__(self, data: ReviewData, path: str) -> None:
        super().__init__()
        self.data = data
        self.PATH = path
        self.contest = getattr(data, "contest", None)

    def names(self) -> dict[str, str]:
        return {str(p["uid"]): str(p["name"]) for p in self.data.people()}

    def titles(self) -> dict[int, str]:
        return {int(p["problem_index"]): str(p["title"]) for p in self.data.problems()}

    def subtitle(self) -> str:
        return f"{len(self.rows)} 项"


class FindingsScreen(ReviewListScreen):
    TITLE = "线索"
    HINTS = (("↵", "查看证据"), ("f", "筛选"), ("/", "搜索"), ("esc", "返回"))
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("f", "cycle_filter", "切换筛选"),
    ]
    FILTERS = ("全部", "高优先级", "未处理", "已处理")
    COLUMNS = (
        ui.Column("等级", 8),
        ui.Column("题目"),
        ui.Column("选手 A"),
        ui.Column("选手 B"),
        ui.Column("相似度", 6, "right"),
        ui.Column("复核", 14),
    )
    EMPTY = "当前筛选下没有线索"

    def __init__(self, data: ReviewData, path: str) -> None:
        super().__init__(data, path)
        self.filter_index = 0
        self._people_names: dict[str, str] = {}
        self._problem_titles: dict[int, str] = {}
        self._all_findings: list[dict[str, Any]] = []

    def table(self) -> list[object]:
        return [Static("", id="filters"), *super().table()]

    def subtitle(self) -> str:
        return "按优先级排序 · 检测线索不等于违规认定"

    def _filtered(self, mode: str) -> list[dict[str, Any]]:
        rows = self._all_findings
        if mode == "高优先级":
            return [
                r for r in rows if not r["is_stale"] and ui.is_high_priority(r["verdict_level"])
            ]
        if mode == "未处理":
            return [r for r in rows if not r["is_stale"] and r["status"] == DEFAULT_REVIEW_STATUS]
        if mode == "已处理":
            return [r for r in rows if not r["is_stale"] and r["status"] != DEFAULT_REVIEW_STATUS]
        return rows

    def items(self) -> list[dict[str, Any]]:
        self._all_findings = self.data.findings()
        return self._filtered(self.FILTERS[self.filter_index])

    def reload(self) -> None:
        self._people_names = self.names()
        self._problem_titles = self.titles()
        super().reload()
        colors = ui.palette(self.app)
        tabs = Text()
        for index, mode in enumerate(self.FILTERS):
            count = len(self._filtered(mode))
            if index == self.filter_index:
                tabs.append(f" {mode} {count} ", style=f"bold {colors.bg} on {colors.accent}")
            else:
                tabs.append(f" {mode} {count} ", style=colors.muted)
            tabs.append(" ")
        self.query_one("#filters", Static).update(tabs)

    def action_cycle_filter(self) -> None:
        self.filter_index = (self.filter_index + 1) % len(self.FILTERS)
        self.reload()

    def _person(self, uid: str) -> Text:
        colors = ui.palette(self.app)
        name = self._people_names.get(uid, uid)
        text = Text(name, style=colors.fg)
        if name != uid:
            text.append(f" {uid}", style=colors.muted)
        return text

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        index = int(row["problem_index"])
        title = self._problem_titles.get(index, "")
        problem = Text(f"{index} ", style=colors.muted)
        problem.append(title or f"题 {index}", style=colors.fg)
        similarity = row["scores"].get("similarity") if isinstance(row["scores"], dict) else None
        return [
            Text("历史", style=colors.muted)
            if row["is_stale"]
            else level_chip(row["verdict_level"], colors),
            problem,
            self._person(str(row["uid_a"])),
            self._person(str(row["uid_b"])),
            ui.percent(similarity) if similarity is not None else Text("—", style=colors.muted),
            status_text(row["status"], colors, row["is_stale"]),
        ]

    def open_index(self, index: int) -> None:
        item = self.selected_row(index)
        if item is not None:
            self.app.push_screen(EvidenceScreen(self.data, self.PATH, item))


# 分数键的展示名；未登记的数值键按原名显示，保证外部插件的分数也能看到。
SCORE_LABELS = {
    "similarity": "指纹",
    "L1": "原文",
    "L2": "去空白",
    "L3": "归一化",
    "rare_score": "稀有片段",
}


class EvidenceScreen(ShellScreen):
    TITLE = "线索证据"
    HINTS = (
        ("j/k", "上/下一条"),
        ("tab", "对照/差异"),
        ("r", "复核"),
        ("m", "标记选手"),
        ("u", "切换 A/B"),
        ("esc", "返回"),
    )
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,h,left", "back", "返回"),
        ("tab", "diff", "对照 / 差异视图"),
        ("shift+tab", "diff", "对照 / 差异视图"),
        ("j,down", "next", "下一条"),
        ("k,up", "previous", "上一条"),
        ("right,l,enter,space", "diff", "对照 / 差异视图"),
        ("g", "first_evidence", "第一条"),
        ("shift+g", "last_evidence", "最后一条"),
        ("r", "review", "复核结论"),
        ("m", "mark", "标记选手"),
        ("u", "switch_person", "切换标记对象 A/B"),
        ("n", "next", "下一条"),
        ("p", "previous", "上一条"),
    ]

    def __init__(self, data: ReviewData, parent_path: str, finding: dict[str, Any]) -> None:
        super().__init__()
        self.data = data
        self.parent_path = parent_path
        self.finding = finding
        self.contest = data.contest
        self.diff_mode = False
        self.person_side = 0
        self._sync_path()

    def _sync_path(self) -> None:
        self.PATH = f"{self.parent_path} › 证据"

    def compose(self) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            yield Static("", id="evidence-head")
            yield Static("", id="evidence-meta")
            with Horizontal(id="code-pair"):
                with VerticalScroll(id="pane-left", classes="source-pane"):
                    yield Static("", id="code-left")
                with VerticalScroll(id="pane-right", classes="source-pane"):
                    yield Static("", id="code-right")
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
        self.render_evidence()

    def on_layout_change(self) -> None:
        self.render_evidence()

    def _position(self) -> tuple[int, int]:
        findings = self.data.findings()
        current = next((i for i, f in enumerate(findings) if self._same(f, self.finding)), -1)
        return current + 1, len(findings)

    def _timeline(self, timeline: dict[str, Any], names: tuple[str, str]) -> Text | None:
        colors = ui.palette(self.app)
        who = timeline.get("who_first")
        if who not in ("A", "B"):
            return None
        first, later = (names[0], names[1]) if who == "A" else (names[1], names[0])
        text = Text(f"{first} 先通过", style=colors.fg)
        if timeline.get("delta_seconds") is not None:
            text.append(
                f"，{later} 晚 {ui.duration(timeline['delta_seconds'])} 通过", style=colors.fg
            )
        if timeline.get("direction_valid"):
            text.append(f" · {later} 首次提交在 {first} 通过之后", style=colors.warn)
        failures = timeline.get("later_failures_before_ac")
        if failures:
            text.append(f" · {later} 通过前失败 {failures} 次", style=colors.muted)
        return text

    def render_evidence(self) -> None:
        colors = ui.palette(self.app)
        finding = self.finding
        scores = finding["scores"] if isinstance(finding["scores"], dict) else {}
        reasons = (
            finding["reasons"] if isinstance(finding["reasons"], list) else [finding["reasons"]]
        )
        a = self.data.person(str(finding["uid_a"]))
        b = self.data.person(str(finding["uid_b"]))
        names = (str(a["name"]), str(b["name"]))
        titles = {int(p["problem_index"]): p["title"] for p in self.data.problems()}
        index = int(finding["problem_index"])
        position, total = self._position()

        head = Text(no_wrap=True)
        if finding["is_stale"]:
            head.append_text(ui.chip("已失效", colors.muted))
        else:
            head.append_text(level_chip(finding["verdict_level"], colors))
        head.append(f"  {index} · {titles.get(index, f'题 {index}')}", style=f"bold {colors.fg}")
        head.append(
            f"  {LANGUAGES.get(finding['language'], finding['language'])}", style=colors.muted
        )
        head.append("    ")
        head.append_text(status_text(finding["status"], colors, finding["is_stale"]))
        if finding.get("note"):
            head.append(f"  “{finding['note']}”", style=colors.muted)
        if position:
            head.append(f"    {position} / {total}", style=colors.muted)
        head.append("\n")
        for side, person in (("A", a), ("B", b)):
            target = (side == "A") == (self.person_side == 0)
            head.append(f"{side} ", style=f"bold {colors.accent}" if target else colors.muted)
            head.append(str(person["name"]), style=f"bold {colors.fg}")
            head.append(f" {person['uid']} ", style=colors.muted)
            head.append_text(mark_text(person, colors))
            if side == "A":
                head.append("   ⇄   ", style=colors.muted)
        self.query_one("#evidence-head", Static).update(head)

        meta = Text()
        numeric = [
            (key, float(value))
            for key, value in scores.items()
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0 <= value <= 1
            and key not in ("template_crowd",)
        ]
        for i, (key, value) in enumerate(numeric):
            if i:
                meta.append("    ")
            meta.append(SCORE_LABELS.get(key, key) + " ", style=colors.muted)
            meta.append_text(
                ui.bar(value, 6, colors.level(finding["verdict_level"]), colors.surface)
            )
            meta.append(f" {value:.0%}", style=f"bold {colors.fg}")
        facts = []
        if "md5_ws_equal" in scores:
            facts.append(("去空白后完全一致", "是" if scores["md5_ws_equal"] else "否"))
        if "template_crowd" in scores:
            facts.append(("同码人数", str(scores["template_crowd"])))
        if facts:
            meta.append("\n")
            for i, (name, value) in enumerate(facts):
                if i:
                    meta.append("    ")
                meta.append(name + " ", style=colors.muted)
                meta.append(value, style=colors.fg)
        timeline = scores.get("timeline")
        line = self._timeline(timeline, names) if isinstance(timeline, dict) else None
        if line is not None:
            meta.append("\n时间线  ", style=colors.muted)
            meta.append_text(line)
        shown = [str(r) for r in reasons if not str(r).startswith(("时间线：", "检测分级："))]
        if shown:
            meta.append("\n依据    ", style=colors.muted)
            meta.append(" · ".join(shown), style=colors.fg)
        self.query_one("#evidence-meta", Static).update(meta)

        left = self.data.representative(str(finding["uid_a"]), index, finding["language"])
        right = self.data.representative(str(finding["uid_b"]), index, finding["language"])
        left_code = left["code"] if left else "（本地无对应提交）"
        right_code = right["code"] if right else "（本地无对应提交）"
        left_pane = self.query_one("#pane-left")
        right_pane = self.query_one("#pane-right")
        if self.diff_mode:
            right_pane.display = False
            left_pane.border_subtitle = ""
            left_pane.border_title = f"差异  A {names[0]} → B {names[1]}"
            self.query_one("#code-left", Static).update(
                _diff_text(left_code, right_code, names, colors)
            )
        else:
            right_pane.display = True
            changed_left, changed_right = _changed_lines(left_code, right_code)
            for pane, view, side, person, row, code, changed in (
                (left_pane, "#code-left", "A", a, left, left_code, changed_left),
                (right_pane, "#code-right", "B", b, right, right_code, changed_right),
            ):
                verdict = f" · {row['verdict']} · {ui.clock(row['submit_time'])}" if row else ""
                pane.border_title = f"{side}  {person['name']}{verdict}"
                self.query_one(view, Static).update(
                    _syntax(code, finding["language"], colors.bg, changed)
                )
            left_pane.border_subtitle = "高亮行与另一侧不同"
        self.refresh_chrome()

    def action_first_evidence(self) -> None:
        self._move(-1000000)

    def action_last_evidence(self) -> None:
        self._move(1000000)

    def action_diff(self) -> None:
        self.diff_mode = not self.diff_mode
        self.render_evidence()

    def action_switch_person(self) -> None:
        self.person_side = 1 - self.person_side
        self.render_evidence()

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
                f"标记选手 {person['name']}",
                MARK_CHOICES,
                person["mark"],
                person["note"],
                hint=f"UID {uid} · 按 u 可切换 A/B",
            ),
            lambda result: self._save_mark(uid, result),
        )

    def _save_mark(self, uid: str, result: tuple[str, str] | None) -> None:
        if result is not None:
            self.data.mark(uid, *result)
            self.notify("人员标记已保存")
            self.render_evidence()

    def action_review(self) -> None:
        if self.finding["is_stale"]:
            self.notify("已失效线索仅供查看", severity="warning")
            return
        self.app.push_screen(
            ChoiceDialog(
                "复核结论",
                REVIEW_CHOICES,
                (self.finding["status"] if self.finding["status"] in REVIEW_STATUSES else ""),
                self.finding.get("note", ""),
                hint="保存后自动跳到下一条待复核线索",
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
            if not item["is_stale"] and item["status"] == DEFAULT_REVIEW_STATUS
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
            a.get(key) == b.get(key)
            for key in ("run_id", "uid_a", "uid_b", "problem_index", "language")
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


def _is_ac(verdict: str) -> bool:
    raw = str(verdict)
    return raw.upper() in ("AC", "ACCEPTED") or any(m in raw for m in ("答案正确", "通过"))


class PeopleScreen(ReviewListScreen):
    TITLE = "选手"
    HINTS = (("↵", "查看"), ("/", "搜索"), ("esc", "返回"))
    COLUMNS = (
        ui.Column("姓名"),
        ui.Column("UID", 14),
        ui.Column("通过", 4, "right"),
        ui.Column("提交", 4, "right"),
        ui.Column("线索", 4, "right"),
        ui.Column("标记", 10),
    )

    def items(self) -> list[dict[str, Any]]:
        solved: dict[str, set[int]] = defaultdict(set)
        submitted: Counter[str] = Counter()
        for row in self.data.submissions():
            submitted[row["uid"]] += 1
            if _is_ac(row["verdict"]):
                solved[row["uid"]].add(int(row["problem_index"]))
        findings: Counter[str] = Counter()
        for f in self.data.findings():
            if not f["is_stale"]:
                findings[str(f["uid_a"])] += 1
                findings[str(f["uid_b"])] += 1
        people = self.data.people()
        for person in people:
            person["solved"] = len(solved[person["uid"]])
            person["submitted"] = submitted[person["uid"]]
            person["findings"] = findings[str(person["uid"])]
        return people

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        return [
            Text(str(row["name"]), style=colors.muted if row["hidden"] else colors.fg),
            Text(str(row["uid"]), style=colors.muted),
            str(row["solved"]),
            str(row["submitted"]),
            Text(str(row["findings"]), style=colors.warn)
            if row["findings"]
            else Text("·", style=colors.muted),
            mark_text(row, colors),
        ]

    def open_index(self, index: int) -> None:
        person = self.selected_row(index)
        if person:
            self.app.push_screen(PersonScreen(self.data, self.PATH, person["uid"]))


class PersonScreen(ReviewListScreen):
    TITLE = "选手"
    HINTS = (("↵", "提交历史"), ("m", "标记"), ("esc", "返回"))
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("m", "mark", "标记选手"),
    ]
    COLUMNS = (
        ui.Column("题目"),
        ui.Column("提交", 4, "right"),
        ui.Column("最终结果", 12),
        ui.Column("线索", 4, "right"),
    )

    def __init__(self, data: ReviewData, path: str, uid: str) -> None:
        person = data.person(uid)
        super().__init__(data, f"{path} › {person['name']}")
        self.uid = uid
        self.TITLE = str(person["name"])

    def subtitle(self) -> str:
        person = self.data.person(self.uid)
        mark = "管理者" if person["hidden"] else ui.MARK_NAMES.get(person["mark"], "未标记")
        note = f" · {person['note']}" if person.get("note") else ""
        return f"UID {self.uid} · {mark}{note}"

    def items(self) -> list[dict[str, Any]]:
        history: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in self.data.submissions(self.uid):
            history[int(row["problem_index"])].append(row)
        findings: Counter[int] = Counter(
            int(f["problem_index"])
            for f in self.data.findings()
            if not f["is_stale"] and self.uid in (f["uid_a"], f["uid_b"])
        )
        rows = []
        for item in self.data.problems():
            index = int(item["problem_index"])
            if index in history:
                rows.append(
                    {
                        **item,
                        "count": len(history[index]),
                        "final": history[index][-1]["verdict"],
                        "solved": any(_is_ac(r["verdict"]) for r in history[index]),
                        "findings": findings[index],
                    }
                )
        return rows

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        problem = Text(f"{row['problem_index']} ", style=colors.muted)
        problem.append(str(row["title"]), style=colors.fg)
        verdict = "通过" if row["solved"] else str(row["final"])
        return [
            problem,
            str(row["count"]),
            Text(verdict, style=colors.ok if row["solved"] else ui.verdict_color(verdict, colors)),
            Text(str(row["findings"]), style=colors.warn)
            if row["findings"]
            else Text("·", style=colors.muted),
        ]

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
            ChoiceDialog(
                f"标记选手 {person['name']}", MARK_CHOICES, person["mark"], person["note"]
            ),
            self._save,
        )

    def _save(self, result: tuple[str, str] | None) -> None:
        if result is not None:
            self.data.mark(self.uid, *result)
            self.notify("人员标记已保存")
            self.refresh_chrome()


class SubmissionScreen(ReviewListScreen):
    TITLE = "提交历史"
    HINTS = (("↵", "查看代码"), ("esc", "返回"))
    COLUMNS = (
        ui.Column("时间", 14),
        ui.Column("结果", 12),
        ui.Column("得分", 5, "right"),
        ui.Column("语言", 7),
        ui.Column("阶段", 6),
        ui.Column("提交 ID"),
    )

    def __init__(self, data: ReviewData, path: str, uid: str, problem: int) -> None:
        super().__init__(data, f"{path} › 题 {problem}")
        self.uid = uid
        self.problem = problem

    def subtitle(self) -> str:
        return f"含未通过提交 · {len(self.rows)} 次"

    def items(self) -> list[dict[str, Any]]:
        return self.data.submissions(self.uid, self.problem)

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        phase = {"contest": "赛中", "before": "赛前", "after": "赛后"}.get(
            row["phase"], row["phase"]
        )
        return [
            Text(ui.clock(row["submit_time"]), style=colors.muted),
            Text(str(row["verdict"]), style=ui.verdict_color(row["verdict"], colors)),
            f"{float(row['score']):g}",
            LANGUAGES.get(row["language"], row["language"]),
            phase,
            Text(str(row["submission_id"]), style=colors.muted),
        ]

    def open_index(self, index: int) -> None:
        if self.selected_row(index):
            self.app.push_screen(CodeScreen(self.data, self.PATH, self.rows, index))


class ProblemsScreen(ReviewListScreen):
    TITLE = "题目"
    HINTS = (("↵", "查看代码"), ("/", "搜索"), ("esc", "返回"))
    COLUMNS = (
        ui.Column("题目"),
        ui.Column("提交人数", 8, "right"),
        ui.Column("通过人数", 8, "right"),
        ui.Column("线索", 4, "right"),
    )

    def items(self) -> list[dict[str, Any]]:
        tried: dict[int, set[str]] = defaultdict(set)
        solved: dict[int, set[str]] = defaultdict(set)
        for row in self.data.submissions():
            index = int(row["problem_index"])
            tried[index].add(row["uid"])
            if _is_ac(row["verdict"]):
                solved[index].add(row["uid"])
        findings: Counter[int] = Counter(
            int(f["problem_index"]) for f in self.data.findings() if not f["is_stale"]
        )
        rows = self.data.problems()
        for row in rows:
            index = int(row["problem_index"])
            row.update(tried=len(tried[index]), solved=len(solved[index]), findings=findings[index])
        return rows

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        problem = Text(f"{row['problem_index']} ", style=colors.muted)
        problem.append(str(row["title"]), style=colors.fg)
        return [
            problem,
            str(row["tried"]),
            str(row["solved"]),
            Text(str(row["findings"]), style=colors.warn)
            if row["findings"]
            else Text("·", style=colors.muted),
        ]

    def open_index(self, index: int) -> None:
        item = self.selected_row(index)
        if item:
            self.app.push_screen(
                ProblemScreen(self.data, self.PATH, int(item["problem_index"]), item["title"])
            )


class ProblemScreen(ReviewListScreen):
    TITLE = "代表代码"
    HINTS = (("↵", "查看代码"), ("s", "排序"), ("esc", "返回"))
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *ShellScreen.BINDINGS,
        ("s", "sort", "切换排序"),
    ]
    ORDERS = ("time", "name", "findings")
    ORDER_NAMES: ClassVar[dict[str, str]] = {
        "time": "通过时间",
        "name": "姓名",
        "findings": "线索数",
    }
    COLUMNS = (
        ui.Column("选手"),
        ui.Column("结果", 12),
        ui.Column("语言", 7),
        ui.Column("提交时间", 14),
        ui.Column("线索", 4, "right"),
        ui.Column("标记", 10),
    )

    def __init__(self, data: ReviewData, path: str, problem: int, name: str) -> None:
        super().__init__(data, f"{path} › {name}")
        self.problem = problem
        self.order = "time"
        self.TITLE = f"{problem} · {name}"

    def subtitle(self) -> str:
        return f"每人一份代表代码 · 按{self.ORDER_NAMES[self.order]}排序"

    def items(self) -> list[dict[str, Any]]:
        self._finding_counts = self.data.finding_counts(self.problem)
        return self.data.representatives(self.problem, self.order)

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        count = self._finding_counts.get(row["uid"], 0)
        return [
            Text(
                str(row["name"] or row["uid"]),
                style=colors.muted if row.get("hidden") else colors.fg,
            ),
            Text(str(row["verdict"]), style=ui.verdict_color(row["verdict"], colors)),
            LANGUAGES.get(row["language"], row["language"]),
            Text(ui.clock(row["submit_time"]), style=colors.muted),
            Text(str(count), style=colors.warn) if count else Text("·", style=colors.muted),
            mark_text(row, colors),
        ]

    def action_sort(self) -> None:
        self.order = self.ORDERS[(self.ORDERS.index(self.order) + 1) % len(self.ORDERS)]
        self.reload()

    def open_index(self, index: int) -> None:
        if self.selected_row(index):
            self.app.push_screen(CodeScreen(self.data, self.PATH, self.rows, index))


class CodeScreen(ShellScreen):
    TITLE = "代码"
    HINTS = (("j/k", "上/下一份"), ("[ ]", "同题前后提交"), ("m", "标记"), ("esc", "返回"))
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,h,left", "back", "返回"),
        ("n,j,down,right,l,enter,space", "next", "下一份"),
        ("p,k,up", "previous", "上一份"),
        ("g", "first_code", "第一份"),
        ("shift+g", "last_code", "最后一份"),
        ("left_square_bracket", "earlier", "同题上一次提交"),
        ("right_square_bracket", "later", "同题下一次提交"),
        ("m", "mark", "标记选手"),
    ]

    def __init__(
        self, data: ReviewData, path: str, items: list[dict[str, Any]], index: int = 0
    ) -> None:
        super().__init__()
        self.data = data
        self.contest = data.contest
        self.items = items
        self.index = index
        self.base_path = path

    def compose(self) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            yield Static("", id="code-meta")
            with VerticalScroll(id="code-pane", classes="source-pane"):
                yield Static("", id="code-body")
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
        self.render_code()

    def on_layout_change(self) -> None:
        self.render_code()

    @property
    def current(self) -> dict[str, Any]:
        return self.items[self.index]

    def render_code(self) -> None:
        colors = ui.palette(self.app)
        row = self.current
        self.PATH = f"{self.base_path} › 代码"
        person = self.data.person(row["uid"])
        meta = Text(str(person["name"]), style=f"bold {colors.fg}")
        meta.append(f" {row['uid']}  ", style=colors.muted)
        meta.append_text(mark_text(person, colors))
        meta.append(f"    第 {self.index + 1} / {len(self.items)} 份", style=colors.muted)
        self.query_one("#code-meta", Static).update(meta)
        pane = self.query_one("#code-pane")
        when = f" · {ui.clock(row['submit_time'])}" if "submit_time" in row else ""
        pane.border_title = (
            f"题 {row['problem_index']} · {row['verdict']} · "
            f"{LANGUAGES.get(row['language'], row['language'])}{when}"
        )
        pane.border_subtitle = str(row["submission_id"])
        self.query_one("#code-body", Static).update(
            _syntax(row["code"], row["language"], colors.bg)
        )
        self.refresh_chrome()

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
            ChoiceDialog(
                f"标记选手 {person['name']}", MARK_CHOICES, person["mark"], person["note"]
            ),
            lambda result: self._save(uid, result),
        )

    def _save(self, uid: str, result: tuple[str, str] | None) -> None:
        if result is not None:
            self.data.mark(uid, *result)
            self.render_code()
