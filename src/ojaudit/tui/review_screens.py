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
from dataclasses import replace
from difflib import SequenceMatcher, unified_diff
from typing import Any, ClassVar

from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.widgets import ListView, Static

from ojaudit.core.reviews import DEFAULT_REVIEW_STATUS
from ojaudit.core.schema import is_accepted
from ojaudit.tui import ui
from ojaudit.tui.code_view import (
    DiffColors,
    ViewOptions,
    align,
    diff_stats,
    prepare_lines,
    rename,
    render_side,
    variable_mapping,
)
from ojaudit.tui.popup import ChoiceNotePopup, MenuPopup
from ojaudit.tui.review_data import (
    VERDICT_NAMES,
    VERDICT_OF,
    ReviewData,
    finding_verdict,
    pair_key,
    pair_scores,
)
from ojaudit.tui.screens import ShellScreen, TableScreen
from ojaudit.tui.splitter import Splitter

LANGUAGES = {"cpp": "C++", "python": "Python", "java": "Java"}


def _syntax(app: Any, code: str, language: str, highlight: set[int] | None = None) -> Syntax:
    lexer = {"cpp": "cpp", "python": "python", "java": "java"}.get(language, "text")
    background = ui.palette(app).bg
    return Syntax(
        code or "",
        lexer,
        theme=getattr(app, "syntax_theme", "monokai"),
        line_numbers=getattr(app, "line_numbers", True),
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
    """线索的复核结论：作弊 / 存疑 / 正常，未复核时显示「待复核」。"""
    if stale:
        return ui.dot("已失效", colors.muted)
    verdict = VERDICT_OF.get(status, "")
    if not verdict:
        return ui.dot(DEFAULT_REVIEW_STATUS, colors.warn)
    return ui.dot(VERDICT_NAMES[verdict], colors.mark(verdict))


def mark_text(person: dict[str, Any], colors: ui.Palette) -> Text:
    if person.get("hidden"):
        return Text("管理者", style=colors.muted)
    mark = person.get("mark", "")
    if mark not in ui.MARK_NAMES:
        return Text("—", style=colors.muted)
    return ui.dot(ui.MARK_NAMES[mark], colors.mark(mark))


def level_chip(level: object, colors: ui.Palette) -> Text:
    return ui.chip(ui.level_name(level), colors.level(level))


class ReviewPopup(ChoiceNotePopup):
    """复核：作弊 / 存疑 / 正常 / 撤销复核，可附备注；返回 (值, 备注)。"""

    def option_text(self, name: str, value: str, colors: ui.Palette) -> Text:
        verdict = value.split(":")[0]
        return Text(name, style=colors.mark(verdict) if verdict in VERDICT_NAMES else colors.muted)


CLEAR = "clear"  # 撤销复核；与「待复核」的空值区分，避免光标默认停在撤销上


def person_choices() -> list[tuple[str, str]]:
    return [(name, verdict) for verdict, name in VERDICT_NAMES.items()] + [("撤销复核", CLEAR)]


def review_person(screen: Any, uid: str, done: Any) -> None:
    """人员页与代码页的复核：直接给这名选手下结论。"""
    data: ReviewData = screen.data
    person = data.person(uid)
    if person["hidden"]:
        screen.notify("管理者不参与复核", severity="warning")
        return

    def save(result: tuple[str, str] | None) -> None:
        if result is None:
            return
        verdict, note = result
        verdict = "" if verdict == CLEAR else verdict
        resolved = data.judge_person(uid, verdict, note, review_settings()["quick_mark"])
        name = VERDICT_NAMES.get(verdict, "未复核")
        extra = f"，并一并处理此人其余线索 {resolved} 条" if resolved else ""
        screen.notify(f"{person['name']}：{name}{extra}")
        done()

    screen.app.push_screen(
        ReviewPopup(f"复核 {person['name']}", person_choices(), person["mark"], person["note"]),
        save,
    )


class ReviewListScreen(TableScreen):
    """比赛内的表格页：共享 ReviewData 与人员（姓名、标记）查找。"""

    TITLE = "列表"

    def __init__(self, data: ReviewData, path: str) -> None:
        super().__init__()
        self.data = data
        self.PATH = path
        self.contest = getattr(data, "contest", None)
        self._people: dict[str, dict[str, Any]] = {}

    def names(self) -> dict[str, str]:
        return {uid: str(p["name"]) for uid, p in self._load_people().items()}

    def _load_people(self) -> dict[str, dict[str, Any]]:
        self._people = {str(p["uid"]): p for p in self.data.people()}
        return self._people

    def person_cell(self, uid: str, show_uid: bool = True) -> Text:
        """人名按人工标记着色：作弊者偏红、正常偏绿、存疑偏黄、管理者灰。"""
        person = self._people.get(uid, {"name": uid, "mark": "", "hidden": False})
        return ui.person_text(
            str(person["name"]),
            uid,
            str(person.get("mark", "")),
            bool(person.get("hidden")),
            ui.palette(self.app),
            show_uid,
        )

    def titles(self) -> dict[int, str]:
        return {int(p["problem_index"]): str(p["title"]) for p in self.data.problems()}

    def subtitle(self) -> str:
        return f"{len(self.rows)} 项"


class FindingsScreen(ReviewListScreen):
    PAGE_ICON = "findings"
    TITLE = "线索"
    HINTS = (("↵", "查看证据"), ("f", "筛选"), ("s", "排序"), ("/", "搜索"), ("←", "返回"))
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *TableScreen.BINDINGS,
        ("f", "cycle_filter", "切换筛选"),
    ]
    FILTERS = ("全部", "高优先级", "未处理", "已处理")
    COLUMNS = (
        ui.Column("等级", 8),
        ui.Column("题", 3),
        ui.Column("题目"),
        ui.Column("选手 A"),
        ui.Column("选手 B"),
        ui.Column("嫌疑度", 9, "right"),
        ui.Column("相似度", 6, "right"),
        ui.Column("复核", 14),
    )
    # 默认按人物对的总嫌疑度降序：同一对选手的多道题排在一起。
    DEFAULT_SORT = (5, True)
    EMPTY = "当前筛选下没有线索"

    def __init__(self, data: ReviewData, path: str) -> None:
        super().__init__(data, path)
        self.filter_index = 0
        self._problem_titles: dict[int, str] = {}
        self._all_findings: list[dict[str, Any]] = []
        self._pairs: dict[tuple[str, str], tuple[int, int]] = {}

    def table(self) -> list[object]:
        return [Static("", id="filters"), *super().table()]

    def subtitle(self) -> str:
        return "嫌疑度 = 同一对选手所有线索的分级加总 · 检测线索不等于违规认定"

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
        self._pairs = pair_scores(self._all_findings)
        return self._filtered(self.FILTERS[self.filter_index])

    def sort_key(self, row: dict[str, Any], column: int) -> Any:
        pair = pair_key(row)
        return {
            0: (-ui.level_rank(row["verdict_level"]), pair),
            1: int(row["problem_index"]),
            2: self._problem_titles.get(int(row["problem_index"]), ""),
            3: str(self._people.get(str(row["uid_a"]), {}).get("name", row["uid_a"])),
            4: str(self._people.get(str(row["uid_b"]), {}).get("name", row["uid_b"])),
            5: (self._pairs.get(pair, (0, 0))[0], ui.Reversed(pair)),
            6: _similarity(row) or 0.0,
            7: str(row["status"]),
        }.get(column)

    def reload(self) -> None:
        self._load_people()
        self._problem_titles = self.titles()
        super().reload()
        colors = ui.palette(self.app)
        tabs = Text()
        self.tab_spans = []
        for index, mode in enumerate(self.FILTERS):
            count = len(self._filtered(mode))
            start = tabs.cell_len
            if index == self.filter_index:
                tabs.append(f" {mode} {count} ", style=f"bold {colors.bg} on {colors.accent}")
            else:
                tabs.append(f" {mode} {count} ", style=colors.muted)
            self.tab_spans.append((start, tabs.cell_len))
            tabs.append(" ")
        self.query_one("#filters", Static).update(tabs)

    def action_cycle_filter(self) -> None:
        self.filter_index = (self.filter_index + 1) % len(self.FILTERS)
        self.reload()

    def on_click(self, event: events.Click) -> None:
        # 点击筛选标签切换面板。
        if event.widget is not None and event.widget.id == "filters":
            for index, (start, end) in enumerate(getattr(self, "tab_spans", [])):
                if start <= event.x - 1 < end:
                    self.filter_index = index
                    self.reload()
                    return

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        index = int(row["problem_index"])
        similarity = _similarity(row)
        score, count = self._pairs.get(pair_key(row), (0, 0))
        suspicion = Text(str(score), style=f"bold {colors.level(0)}" if score >= 5 else colors.fg)
        suspicion.append(f" ·{count}题", style=colors.muted)
        return [
            Text("历史", style=colors.muted)
            if row["is_stale"]
            else level_chip(row["verdict_level"], colors),
            Text(ui.problem_label(index), style=f"bold {colors.fg}"),
            Text(self._problem_titles.get(index, ""), style=colors.fg),
            self.person_cell(str(row["uid_a"])),
            self.person_cell(str(row["uid_b"])),
            suspicion if score else Text("—", style=colors.muted),
            ui.percent(similarity) if similarity is not None else Text("—", style=colors.muted),
            status_text(row["status"], colors, row["is_stale"]),
        ]

    def open_index(self, index: int) -> None:
        item = self.selected_row(index)
        if item is not None:
            self.app.push_screen(EvidenceScreen(self.data, self.PATH, item, sequence=self.rows))


def _similarity(row: dict[str, Any]) -> float | None:
    scores = row.get("scores")
    value = scores.get("similarity") if isinstance(scores, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


# 分数键的展示名；未登记的数值键按原名显示，保证外部插件的分数也能看到。
SCORE_LABELS = {
    "similarity": "指纹",
    "L1": "原文",
    "L2": "去空白",
    "L3": "归一化",
    "rare_score": "稀有片段",
}


class SyncScroll(ScrollableContainer):
    """两侧代码同步滚动：任一侧滚动时，另一侧滚到相同位置。"""

    partner: SyncScroll | None = None
    _syncing = False

    def watch_scroll_y(self, old: float, new: float) -> None:
        super().watch_scroll_y(old, new)
        self._sync()

    def watch_scroll_x(self, old: float, new: float) -> None:
        super().watch_scroll_x(old, new)
        self._sync()

    def _sync(self) -> None:
        partner = self.partner
        if partner is None or self._syncing or not partner.display:
            return
        partner._syncing = True
        partner.scroll_to(self.scroll_x, self.scroll_y, animate=False)
        partner._syncing = False


# 视图开关：(按键, 名称, ViewOptions 字段)。
VIEW_TOGGLES = (
    ("f", "统一格式", "normalize"),
    ("c", "去注释", "comments"),
    ("i", "忽略头文件", "boilerplate"),
    ("v", "变量对齐", "rename"),
)


def _view_options() -> ViewOptions:
    from ojaudit.core.config import load_config

    saved = load_config().get("evidence", {})
    saved = saved if isinstance(saved, dict) else {}
    return ViewOptions(**{name: bool(saved.get(name, True)) for _, _, name in VIEW_TOGGLES})


def _save_view_options(options: ViewOptions) -> None:
    from ojaudit.core.config import load_config, save_config

    config = load_config()
    config["evidence"] = {name: getattr(options, name) for _, _, name in VIEW_TOGGLES}
    save_config(config)


def nowcoder_links(
    contest: Any, finding: dict[str, Any], left: Any, right: Any
) -> list[tuple[str, str]]:
    """牛客官网链接：A、B 两份提交、题目与比赛页。其他平台暂无链接。"""
    if getattr(contest, "platform", "") != "nowcoder":
        return []
    base = "https://ac.nowcoder.com/acm/contest"
    links = []
    for side, row in (("A 提交", left), ("B 提交", right)):
        if row:
            links.append((side, f"{base}/view-submission?submissionId={row['submission_id']}"))
    letter = ui.problem_label(finding["problem_index"])
    links.append(("题目", f"{base}/{contest.contest_id}/{letter}"))
    links.append(("比赛", f"{base}/{contest.contest_id}"))
    return links


class EvidenceScreen(ShellScreen):
    PAGE_ICON = "evidence"
    TITLE = "线索证据"
    HINTS = (
        ("↵", "复核"),
        ("↑↓", "上/下一条"),
        ("tab", "对照/差异"),
        ("o", "打开牛客"),
        ("←", "返回"),
    )
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,h,left", "back", "返回"),
        ("enter,space", "review", "复核"),
        ("tab,shift+tab", "diff", "对照 / 差异视图"),
        ("j,down,n", "next", "下一条"),
        ("k,up,p", "previous", "上一条"),
        ("g", "first_evidence", "第一条"),
        ("shift+g", "last_evidence", "最后一条"),
        ("o", "links", "在浏览器打开牛客页面"),
        ("f", "toggle_view('normalize')", "统一格式（空格、缩进、括号）"),
        ("c", "toggle_view('comments')", "去掉注释"),
        ("i", "toggle_view('boilerplate')", "忽略头文件与 IO 样板"),
        ("v", "toggle_view('rename')", "变量名对齐"),
        ("a", "toggle_all", "规范化选项全开 / 全关"),
    ]

    def __init__(
        self,
        data: ReviewData,
        parent_path: str,
        finding: dict[str, Any],
        sequence: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.data = data
        self.parent_path = parent_path
        self.finding = finding
        self.contest = data.contest
        self.diff_mode = False
        # 翻页顺序与上一页列表一致（列表可能按嫌疑度等排序）。
        self.sequence = [self._key(item) for item in sequence] if sequence else None
        self.options = _view_options()
        self.link_spans: list[tuple[int, int, str]] = []
        self.toggle_spans: list[tuple[int, int, str]] = []
        self._sync_path()

    def _sync_path(self) -> None:
        self.PATH = f"{self.parent_path} › 证据"

    def compose(self) -> ComposeResult:
        yield from self.chrome_top()
        with Vertical(id="body"):
            with Vertical(id="evidence-panel", classes="panel"):
                yield Static("", id="evidence-head")
                yield Static("", id="evidence-meta")
            yield Static("", id="view-bar")
            with Horizontal(id="code-pair"):
                with SyncScroll(id="pane-left", classes="source-pane"):
                    yield Static("", id="code-left")
                yield Splitter("pane-left", "evidence", minimum=24, keep_right=24)
                with SyncScroll(id="pane-right", classes="source-pane"):
                    yield Static("", id="code-right")
        yield from self.chrome_bottom()

    def on_mount(self) -> None:
        left, right = (
            self.query_one("#pane-left", SyncScroll),
            self.query_one("#pane-right", SyncScroll),
        )
        left.partner, right.partner = right, left
        self.render_evidence()

    def on_layout_change(self) -> None:
        self.render_evidence()

    # ── 线索顺序 ────────────────────────────────────────

    @staticmethod
    def _key(item: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(item.get(k) for k in ("run_id", "uid_a", "uid_b", "problem_index", "language"))

    def _findings(self) -> list[dict[str, Any]]:
        findings = self.data.findings()
        if not self.sequence:
            return findings
        by_key = {self._key(item): item for item in findings}
        ordered = [by_key[key] for key in self.sequence if key in by_key]
        return ordered or findings

    @staticmethod
    def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
        return EvidenceScreen._key(a) == EvidenceScreen._key(b)

    def _position(self) -> tuple[int, int]:
        findings = self._findings()
        current = next((i for i, f in enumerate(findings) if self._same(f, self.finding)), -1)
        return current + 1, len(findings)

    # ── 渲染 ────────────────────────────────────────────

    def _timeline(self, timeline: dict[str, Any], people: tuple[Text, Text]) -> Text | None:
        colors = ui.palette(self.app)
        who = timeline.get("who_first")
        if who not in ("A", "B"):
            return None
        first, later = (people[0], people[1]) if who == "A" else (people[1], people[0])
        text = first.copy()
        text.append(" 先通过", style=colors.fg)
        if timeline.get("delta_seconds") is not None:
            text.append(" → ", style=colors.muted)
            text.append_text(later.copy())
            text.append(f" 晚 {ui.duration(timeline['delta_seconds'])} 通过", style=colors.fg)
        if timeline.get("direction_valid"):
            text.append("  首次提交在对方通过之后", style=f"bold {colors.warn}")
        failures = timeline.get("later_failures_before_ac")
        if failures:
            text.append(f"  通过前失败 {failures} 次", style=colors.muted)
        return text

    def _person(self, person: dict[str, Any]) -> Text:
        return ui.person_text(
            str(person["name"]),
            str(person["uid"]),
            str(person.get("mark", "")),
            bool(person.get("hidden")),
            ui.palette(self.app),
            show_uid=False,
        )

    def render_evidence(self) -> None:
        colors = ui.palette(self.app)
        finding = self.finding
        scores = finding["scores"] if isinstance(finding["scores"], dict) else {}
        a = self.data.person(str(finding["uid_a"]))
        b = self.data.person(str(finding["uid_b"]))
        titles = {int(p["problem_index"]): p["title"] for p in self.data.problems()}
        index = int(finding["problem_index"])
        position, total = self._position()
        language = finding["language"]
        left = self.data.representative(str(finding["uid_a"]), index, language)
        right = self.data.representative(str(finding["uid_b"]), index, language)

        panel = self.query_one("#evidence-panel")
        panel.border_title = f" 线索 {position}/{total} " if position else " 线索 "

        # 第一行：等级、题目、语言、复核状态；右侧是可点击的牛客链接。
        head = Text(no_wrap=True)
        if finding["is_stale"]:
            head.append_text(ui.chip("已失效", colors.muted))
        else:
            head.append_text(level_chip(finding["verdict_level"], colors))
        head.append(f"  {ui.problem_label(index)}", style=f"bold {colors.accent}")
        head.append(f" {titles.get(index, '')}", style=f"bold {colors.fg}")
        head.append(f"  {LANGUAGES.get(language, language)}", style=colors.muted)
        head.append("   ")
        head.append_text(status_text(finding["status"], colors, finding["is_stale"]))
        if finding.get("note"):
            head.append(f"  “{finding['note']}”", style=colors.muted)
        links = nowcoder_links(self.contest, finding, left, right)
        tail = Text(no_wrap=True)
        spans = []
        for name, url in links:
            if tail:
                tail.append("  ")
            start = tail.cell_len
            tail.append(f"↗ {name}", style=f"underline {colors.accent}")
            spans.append((start, tail.cell_len, url))
        width = max(panel.size.width - 4, 40)
        gap = max(width - head.cell_len - tail.cell_len, 2)
        head.append(" " * gap)
        offset = head.cell_len
        head.append_text(tail)
        self.link_spans = [(offset + s0, offset + s1, url) for s0, s1, url in spans]
        self.query_one("#evidence-head", Static).update(head)

        # 第二至四行：相似度、时间线、依据。
        meta = Text()
        meta.append("相似度  ", style=colors.muted)
        numeric = [
            (key, float(value))
            for key, value in scores.items()
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0 <= value <= 1
            and key != "template_crowd"
        ]
        for i, (key, value) in enumerate(numeric):
            if i:
                meta.append("   ")
            tone = colors.danger if value >= 0.9 else colors.warn if value >= 0.75 else colors.muted
            meta.append(SCORE_LABELS.get(key, key) + " ", style=colors.muted)
            meta.append_text(ui.bar(value, 5, tone, colors.surface))
            meta.append(f" {value:.0%}", style=f"bold {tone}")
        people = (self._person(a), self._person(b))
        timeline = scores.get("timeline")
        line = self._timeline(timeline, people) if isinstance(timeline, dict) else None
        if line is not None:
            meta.append("\n时间线  ", style=colors.muted)
            meta.append_text(line)
        facts = []
        if "md5_ws_equal" in scores:
            facts.append(
                Text("去空白后完全一致", style=f"bold {colors.danger}")
                if scores["md5_ws_equal"]
                else Text("去空白后不完全一致", style=colors.fg)
            )
        if "template_crowd" in scores:
            facts.append(Text(f"同码 {scores['template_crowd']} 人", style=colors.fg))
        rare = next(
            (r for r in finding.get("reasons", []) if str(r).startswith("稀有片段共享")), ""
        )
        if rare:
            facts.append(Text(f"共享稀有片段 {str(rare).split('：')[-1]} 个", style=colors.fg))
        if facts:
            meta.append("\n依据    ", style=colors.muted)
            for i, fact in enumerate(facts):
                if i:
                    meta.append(" · ", style=colors.muted)
                meta.append_text(fact)
        self.query_one("#evidence-meta", Static).update(meta)
        self._render_view_bar()
        self._render_code(a, b, left, right)
        self.refresh_chrome()

    def _render_view_bar(self) -> None:
        colors = ui.palette(self.app)
        bar = Text(no_wrap=True)
        self.toggle_spans = []
        for mode, name in ((False, "对照"), (True, "差异")):
            start = bar.cell_len
            if self.diff_mode == mode:
                bar.append(f" {name} ", style=f"bold {colors.bg} on {colors.accent}")
            else:
                bar.append(f" {name} ", style=colors.muted)
            self.toggle_spans.append((start, bar.cell_len, "diff"))
        bar.append("   ")
        for key, name, field in VIEW_TOGGLES:
            on = getattr(self.options, field)
            start = bar.cell_len
            bar.append(key, style=f"bold {colors.accent}")
            bar.append(" ✓ " if on else " · ", style=colors.ok if on else colors.muted)
            bar.append(name, style=colors.fg if on else colors.muted)
            self.toggle_spans.append((start, bar.cell_len, f"toggle_view('{field}')"))
            bar.append("   ")
        self.query_one("#view-bar", Static).update(bar)

    def _render_code(self, a: dict[str, Any], b: dict[str, Any], left: Any, right: Any) -> None:
        colors = ui.palette(self.app)
        language = self.finding["language"]
        left_code = left["code"] if left else "（本地无对应提交）"
        right_code = right["code"] if right else "（本地无对应提交）"
        options = self.options
        lines_a = prepare_lines(left_code, language, options)
        lines_b = prepare_lines(right_code, language, options)
        renamed_marks = None
        mapping: dict[str, str] = {}
        if options.rename:
            mapping = variable_mapping(lines_a, lines_b, language)
            lines_b, renamed_marks = rename(lines_b, mapping)
        rows = align(lines_a, lines_b, ignore_space=options.normalize)
        stats = diff_stats(rows)
        left_pane = self.query_one("#pane-left", SyncScroll)
        right_pane = self.query_one("#pane-right", SyncScroll)
        if self.diff_mode:
            right_pane.display = False
            self.query_one(Splitter).display = False
            left_pane.border_title = f"差异  A {a['name']} → B {b['name']}"
            left_pane.border_subtitle = ""
            self.query_one("#code-left", Static).update(
                _unified(lines_a, lines_b, (str(a["name"]), str(b["name"])), colors)
            )
            return
        right_pane.display = True
        self.query_one(Splitter).display = True
        tone = DiffColors(
            change=_tint(colors.warn, colors),
            change_strong=_tint(colors.warn, colors, 0.45),
            delete=_tint(colors.danger, colors),
            insert=_tint(colors.ok, colors),
            filler=_tint(colors.muted, colors, 0.12),
            muted=colors.muted,
            renamed=colors.accent,
        )
        theme = getattr(self.app, "syntax_theme", "monokai")
        numbers = getattr(self.app, "line_numbers", True)
        for pane, view, side, person, row, lines, other, marks in (
            (left_pane, "#code-left", "a", a, left, lines_a, lines_b, None),
            (right_pane, "#code-right", "b", b, right, lines_b, lines_a, renamed_marks),
        ):
            title = Text(side.upper() + "  ", style=f"bold {colors.accent}")
            title.append_text(self._person(person))
            if row:
                title.append(
                    f" · {row['verdict']} · {ui.clock(row['submit_time'])}", style=colors.fg
                )
            pane.border_title = title
            width = max(pane.size.width - 4, 20)
            self.query_one(view, Static).update(
                render_side(rows, side, lines, other, language, theme, tone, width, numbers, marks)
            )
        summary = f"相同 {stats['equal']} 行 · 不同 {stats['change']} 行 · 仅一侧 {stats['delete'] + stats['insert']} 行"
        if mapping:
            summary += f" · 已对齐变量 {len(mapping)} 个（下划线）"
        left_pane.border_subtitle = summary
        right_pane.border_subtitle = ""

    # ── 交互 ────────────────────────────────────────────

    def on_click(self, event: events.Click) -> None:
        widget = event.widget
        if widget is None:
            return
        spans = {"evidence-head": self.link_spans, "view-bar": self.toggle_spans}.get(
            widget.id or ""
        )
        if not spans:
            return
        x = event.x - (1 if widget.id == "view-bar" else 0)
        for start, end, target in spans:
            if start <= x < end:
                event.stop()
                if target.startswith("http"):
                    self.app.open_url(target)
                else:
                    self.call_later(self.run_action, target)
                return

    def action_links(self) -> None:
        index = int(self.finding["problem_index"])
        language = self.finding["language"]
        left = self.data.representative(str(self.finding["uid_a"]), index, language)
        right = self.data.representative(str(self.finding["uid_b"]), index, language)
        links = nowcoder_links(self.contest, self.finding, left, right)
        if not links:
            self.notify("这个平台没有可打开的官网链接", severity="warning")
            return
        self.app.push_screen(
            MenuPopup("打开牛客页面", [(name, url) for name, url in links]),
            lambda url: url and self.app.open_url(url),
        )

    def action_toggle_view(self, field: str) -> None:
        self.options = replace(self.options, **{field: not getattr(self.options, field)})
        _save_view_options(self.options)
        self.render_evidence()

    def action_toggle_all(self) -> None:
        on = not all(getattr(self.options, field) for _, _, field in VIEW_TOGGLES)
        self.options = ViewOptions(**{field: on for _, _, field in VIEW_TOGGLES})
        _save_view_options(self.options)
        self.render_evidence()

    def action_first_evidence(self) -> None:
        self._move(-1000000)

    def action_last_evidence(self) -> None:
        self._move(1000000)

    def action_diff(self) -> None:
        self.diff_mode = not self.diff_mode
        self.render_evidence()

    def review_choices(self) -> tuple[list[tuple[str, str]], str]:
        a = self.data.person(str(self.finding["uid_a"]))
        b = self.data.person(str(self.finding["uid_b"]))
        choices = [
            ("作弊 · 双方", "cheater"),
            (f"作弊 · 仅 {a['name']}", "cheater:a"),
            (f"作弊 · 仅 {b['name']}", "cheater:b"),
            ("存疑", "suspect"),
            ("正常", "normal"),
            ("撤销复核", CLEAR),
        ]
        current = finding_verdict(self.finding)
        if current == "cheater":
            cheats = (a["mark"] == "cheater", b["mark"] == "cheater")
            current = {(True, False): "cheater:a", (False, True): "cheater:b"}.get(
                cheats, "cheater"
            )
        return choices, current

    def action_review(self) -> None:
        if self.finding["is_stale"]:
            self.notify("已失效线索仅供查看", severity="warning")
            return
        choices, current = self.review_choices()
        self.app.push_screen(
            ReviewPopup("复核", choices, current, self.finding.get("note", "")),
            self._save_review,
        )

    def _save_review(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        value, note = result
        verdict, _, side = ("" if value == CLEAR else value).partition(":")
        who = (str(self.finding["uid_" + side]),) if side else None
        settings = review_settings()
        resolved = self.data.judge_finding(self.finding, verdict, note, who, settings["quick_mark"])
        if resolved:
            self.notify(f"已复核，并一并处理作弊者其余线索 {resolved} 条")
        self._refresh_current()
        if verdict and settings["auto_advance"]:
            self._advance()
        else:
            self.render_evidence()

    def _advance(self) -> None:
        """跳到下一条待复核线索（按列表顺序，循环）。"""
        findings = self._findings()
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
            self.render_evidence()
            self.notify("当前没有更多待复核线索")

    def _refresh_current(self) -> None:
        for item in self.data.findings():
            if self._same(item, self.finding):
                self.finding = item
                break

    def _move(self, delta: int) -> None:
        findings = self._findings()
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


def review_settings() -> dict[str, bool]:
    from ojaudit.core.config import load_config

    saved = load_config().get("review", {})
    saved = saved if isinstance(saved, dict) else {}
    return {
        "auto_advance": bool(saved.get("auto_advance", True)),
        "quick_mark": bool(saved.get("quick_mark", True)),
    }


def _tint(color: str, colors: ui.Palette, amount: float = 0.22) -> str:
    """差异底色：把语义色按比例混入背景，避免整行纯色太刺眼。"""
    if color.startswith("#") and colors.bg.startswith("#"):
        return ui._mix(color, colors.bg, amount)
    return {colors.warn: "yellow", colors.danger: "red", colors.ok: "green"}.get(
        color, "bright_black"
    )


def _unified(
    lines_a: list[str], lines_b: list[str], names: tuple[str, str], colors: ui.Palette
) -> Text:
    return _diff_text("\n".join(lines_a), "\n".join(lines_b), names, colors)


class PeopleScreen(ReviewListScreen):
    PAGE_ICON = "people"
    TITLE = "选手"
    HINTS = (
        ("↵", "查看"),
        ("a", "设为/取消管理者"),
        ("s", "排序"),
        ("/", "搜索"),
        ("←", "返回"),
    )
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *TableScreen.BINDINGS,
        ("a", "toggle_manager", "设为 / 取消管理者"),
    ]
    DEFAULT_SORT = (4, True)
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
            if is_accepted(row["verdict"]):
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

    def sort_key(self, row: dict[str, Any], column: int) -> Any:
        return {
            0: str(row["name"]),
            1: str(row["uid"]),
            2: row["solved"],
            3: row["submitted"],
            4: row["findings"],
            5: {"cheater": 0, "suspect": 1, "normal": 3}.get(str(row.get("mark", "")), 2),
        }.get(column)

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        return [
            ui.person_text(
                str(row["name"]), str(row["uid"]), row["mark"], row["hidden"], colors, False
            ),
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

    def action_toggle_manager(self) -> None:
        view = self.query_one("#items", ListView)
        person = self.selected_row(view.index if view.index is not None else -1)
        if not person:
            return
        manager = not person["hidden"]
        self.data.set_manager(str(person["uid"]), manager)
        self.reload()
        self.notify(f"已把 {person['name']} {'设为' if manager else '移出'}管理者")


class PersonScreen(ReviewListScreen):
    PAGE_ICON = "person"
    TITLE = "选手"
    HINTS = (("↵", "复核"), ("→", "提交历史"), ("←", "返回"))
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        *TableScreen.BINDINGS,
    ]
    COLUMNS = (
        ui.Column("题", 3),
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

    def heading(self) -> Text:
        colors = ui.palette(self.app)
        person = self.data.person(self.uid)
        text = ui.person_text(
            str(person["name"]), self.uid, person["mark"], person["hidden"], colors, False
        )
        text.stylize("bold")
        text.append("   " + self.subtitle(), style=colors.muted)
        return text

    def subtitle(self) -> str:
        person = self.data.person(self.uid)
        if person["hidden"]:
            mark = "管理者"
        elif person["mark"] in ui.MARK_NAMES:
            mark = ui.MARK_NAMES[person["mark"]]
        else:
            # 没被检测筛出的人不需要人工复核，按正常处理。
            involved = any(
                not f["is_stale"] and self.uid in (str(f["uid_a"]), str(f["uid_b"]))
                for f in self.data.findings()
            )
            mark = "待复核" if involved else "无线索 · 按正常处理"
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
                        "solved": any(is_accepted(r["verdict"]) for r in history[index]),
                        "findings": findings[index],
                    }
                )
        return rows

    def sort_key(self, row: dict[str, Any], column: int) -> Any:
        return {
            0: int(row["problem_index"]),
            1: str(row["title"]),
            2: row["count"],
            3: (row["solved"], str(row["final"])),
            4: row["findings"],
        }.get(column)

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        verdict = "通过" if row["solved"] else str(row["final"])
        return [
            Text(ui.problem_label(row["problem_index"]), style=f"bold {colors.fg}"),
            Text(str(row["title"]), style=colors.fg),
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

    def action_activate(self) -> None:
        review_person(self, self.uid, self.reload)


class SubmissionScreen(ReviewListScreen):
    PAGE_ICON = "submissions"
    TITLE = "提交历史"
    HINTS = (("↵", "查看代码"), ("←", "返回"))
    COLUMNS = (
        ui.Column("时间", 14),
        ui.Column("结果", 12),
        ui.Column("得分", 5, "right"),
        ui.Column("语言", 7),
        ui.Column("阶段", 6),
        ui.Column("提交 ID"),
    )

    def __init__(self, data: ReviewData, path: str, uid: str, problem: int) -> None:
        super().__init__(data, f"{path} › {ui.problem_label(problem)}")
        self.uid = uid
        self.problem = problem

    def subtitle(self) -> str:
        return f"含未通过提交 · {len(self.rows)} 次"

    def items(self) -> list[dict[str, Any]]:
        return self.data.submissions(self.uid, self.problem)

    def sort_key(self, row: dict[str, Any], column: int) -> Any:
        return {
            0: int(row["submit_time"]),
            1: str(row["verdict"]),
            2: float(row["score"]),
            3: str(row["language"]),
            4: str(row["phase"]),
            5: str(row["submission_id"]),
        }.get(column)

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
    PAGE_ICON = "problems"
    TITLE = "题目"
    HINTS = (("↵", "查看代码"), ("s", "排序"), ("/", "搜索"), ("←", "返回"))
    COLUMNS = (
        ui.Column("题", 3),
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
            if is_accepted(row["verdict"]):
                solved[index].add(row["uid"])
        findings: Counter[int] = Counter(
            int(f["problem_index"]) for f in self.data.findings() if not f["is_stale"]
        )
        rows = self.data.problems()
        for row in rows:
            index = int(row["problem_index"])
            row.update(tried=len(tried[index]), solved=len(solved[index]), findings=findings[index])
        return rows

    def sort_key(self, row: dict[str, Any], column: int) -> Any:
        return {
            0: int(row["problem_index"]),
            1: str(row["title"]),
            2: row["tried"],
            3: row["solved"],
            4: row["findings"],
        }.get(column)

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        return [
            Text(ui.problem_label(row["problem_index"]), style=f"bold {colors.fg}"),
            Text(str(row["title"]), style=colors.fg),
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
    PAGE_ICON = "problem"
    TITLE = "代表代码"
    HINTS = (("↵", "查看代码"), ("s", "排序"), ("←", "返回"))
    COLUMNS = (
        ui.Column("选手"),
        ui.Column("结果", 12),
        ui.Column("语言", 7),
        ui.Column("提交时间", 14),
        ui.Column("线索", 4, "right"),
        ui.Column("标记", 10),
    )

    def __init__(self, data: ReviewData, path: str, problem: int, name: str) -> None:
        super().__init__(data, f"{path} › {ui.problem_label(problem)}")
        self.problem = problem
        self.TITLE = f"{ui.problem_label(problem)} · {name}"
        self._finding_counts: dict[str, int] = {}

    def subtitle(self) -> str:
        return "每人一份代表代码（最高分 → 最长 → 最早）"

    def items(self) -> list[dict[str, Any]]:
        self._finding_counts = self.data.finding_counts(self.problem)
        return self.data.representatives(self.problem, "time")

    def sort_key(self, row: dict[str, Any], column: int) -> Any:
        return {
            0: str(row["name"] or row["uid"]),
            1: str(row["verdict"]),
            2: str(row["language"]),
            3: int(row["submit_time"]),
            4: self._finding_counts.get(row["uid"], 0),
            5: {"cheater": 0, "suspect": 1, "normal": 3}.get(str(row.get("mark", "")), 2),
        }.get(column)

    def cells(self, row: dict[str, Any]) -> Sequence[str | Text]:
        colors = ui.palette(self.app)
        count = self._finding_counts.get(row["uid"], 0)
        return [
            ui.person_text(
                str(row["name"] or row["uid"]),
                str(row["uid"]),
                str(row.get("mark", "")),
                bool(row.get("hidden")),
                colors,
                False,
            ),
            Text(str(row["verdict"]), style=ui.verdict_color(row["verdict"], colors)),
            LANGUAGES.get(row["language"], row["language"]),
            Text(ui.clock(row["submit_time"]), style=colors.muted),
            Text(str(count), style=colors.warn) if count else Text("·", style=colors.muted),
            mark_text(row, colors),
        ]

    def open_index(self, index: int) -> None:
        if self.selected_row(index):
            self.app.push_screen(CodeScreen(self.data, self.PATH, self.rows, index))


class CodeScreen(ShellScreen):
    PAGE_ICON = "code"
    TITLE = "代码"
    HINTS = (
        ("↵", "复核"),
        ("↑↓", "上/下一份"),
        ("[", "前一次提交"),
        ("]", "后一次提交"),
        ("←", "返回"),
    )
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,h,left", "back", "返回"),
        ("enter,space", "review", "复核此人"),
        ("n,j,down", "next", "下一份"),
        ("p,k,up", "previous", "上一份"),
        ("g", "first_code", "第一份"),
        ("shift+g", "last_code", "最后一份"),
        ("left_square_bracket", "earlier", "同题上一次提交"),
        ("right_square_bracket", "later", "同题下一次提交"),
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
        meta = ui.person_text(
            str(person["name"]), str(row["uid"]), person["mark"], person["hidden"], colors, False
        )
        meta.stylize("bold")
        meta.append(f" {row['uid']}  ", style=colors.muted)
        meta.append_text(mark_text(person, colors))
        meta.append(f"    第 {self.index + 1} / {len(self.items)} 份", style=colors.muted)
        self.query_one("#code-meta", Static).update(meta)
        pane = self.query_one("#code-pane")
        when = f" · {ui.clock(row['submit_time'])}" if "submit_time" in row else ""
        pane.border_title = (
            f"{ui.problem_label(row['problem_index'])} · {row['verdict']} · "
            f"{LANGUAGES.get(row['language'], row['language'])}{when}"
        )
        pane.border_subtitle = str(row["submission_id"])
        self.query_one("#code-body", Static).update(_syntax(self.app, row["code"], row["language"]))
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

    def action_review(self) -> None:
        review_person(self, str(self.current["uid"]), self.render_code)
