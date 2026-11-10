"""
Module: TUI / popup
Description: lazygit 风格的弹窗：标题写在边框上、操作提示写在下边框，无按钮、无遮罩；
    以及 nvim 风格的底部 / 搜索行。
Scope: TUI
Notes:
- 所有弹窗 Esc 取消、Enter 确认；输入类弹窗可带实时校验，校验不通过时 Enter 不会关闭。
- 是 / 否确认可以用 ←/→（h/l、Tab）选择、Enter 确定，也可以直接按 y / n 或点击。
- 与页面导航一致：选项弹窗里 ← 返回（同 Esc）、→ 确定（同 Enter）；输入框获得焦点时方向键与
  字母键照常用于编辑。
- 密码输入框只把值交给调用方，不显示、不记录。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, ClassVar

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from ojaudit.tui import ui
from ojaudit.tui.icons import label

Hint = tuple[str, str, str]  # (按键显示, 说明, 动作)


class HintRow(Static):
    """弹窗底部唯一的一行提示：显示「按键 说明」，每一项也可以直接点击执行。"""

    DEFAULT_CSS = """
    HintRow { height: 1; width: 100%; text-align: right; margin-top: 1; }
    """

    def __init__(self, hints: Sequence[Hint]) -> None:
        super().__init__("", classes="popup-hints")
        self.hints = list(hints)
        self.selected: int | None = None
        self.spans: list[tuple[int, int, str]] = []

    def on_mount(self) -> None:
        self.show(self.hints, self.selected)

    def show(self, hints: Sequence[Hint], selected: int | None = None) -> None:
        """selected 为当前选中项的序号：整项反色显示，Enter 执行它。"""
        colors = ui.palette(self.app)
        self.hints = list(hints)
        self.selected = selected
        text = Text(no_wrap=True)
        self.spans = []
        for index, (key, name, action) in enumerate(self.hints):
            if index:
                text.append("  " if selected is not None else "   ")
            start = text.cell_len
            if index == selected:
                text.append(f" {key} {name} ", style=f"bold {colors.bg} on {colors.accent}")
            elif selected is not None:
                text.append(" ")
                text.append(key, style=f"bold {colors.accent}")
                text.append(f" {name} ", style=colors.muted)
            else:
                text.append(key, style=f"bold {colors.accent}")
                text.append(" " + name, style=colors.fg if index == 0 else colors.muted)
            self.spans.append((start, text.cell_len, action))
        self.update(text)

    def on_click(self, event: events.Click) -> None:
        # 右对齐：先换算成文字内的列，再找被点中的那一项。
        total = self.spans[-1][1] if self.spans else 0
        x = event.x - (self.size.width - total)
        for start, end, action in self.spans:
            if start <= x < end:
                event.stop()
                self.screen.call_later(self.screen.run_action, action)
                return


class Popup(ModalScreen[Any]):
    """弹窗基类：居中、透明背景、单层边框；标题在上边框，底部一行可点击的按键提示；
    点击弹窗外部等同于取消。"""

    HINTS: ClassVar[Sequence[Hint]] = (("←", "返回", "cancel"),)
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消", priority=True),
        # 非优先绑定：输入框有焦点时 ← 先由输入框移动光标。
        Binding("left", "back", "返回", show=False),
    ]
    DEFAULT_CSS = """
    Popup { align: center middle; background: transparent; }
    """
    WIDTH = 64
    ICON = "open"

    def __init__(self, title: str, hints: Sequence[Hint] | None = None) -> None:
        super().__init__()
        self.popup_title = title
        self.hints = list(hints if hints is not None else self.HINTS)

    def frame(self, *children: Any, id: str | None = None) -> Vertical:
        box = Vertical(*children, HintRow(self.hints), id=id, classes="popup dialog")
        box.styles.width = self.WIDTH
        return box

    def set_hints(self, hints: Sequence[Hint]) -> None:
        self.hints = list(hints)
        self.query_one(HintRow).show(self.hints)

    def on_mount(self) -> None:
        box = self.query_one(".popup")
        box.border_title = f" {label(self.ICON, self.popup_title, self.app.nerd_font)} "

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_back(self) -> None:
        self.action_cancel()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # 输入框有焦点时，导航键（← / h / l / j / k / →）留给输入框编辑文字。
        navigation = {"back", "choose", "cursor_down", "cursor_up"}
        return not (action in navigation and isinstance(self.focused, Input))

    def on_click(self, event: events.Click) -> None:
        box = self.query_one(".popup")
        if not box.region.contains(event.screen_x, event.screen_y):
            event.stop()
            self.action_cancel()


class InputPopup(Popup):
    """单行输入。validate 返回错误文字或 None；info 根据输入实时给出说明（如命中数）。"""

    HINTS: ClassVar[Sequence[Hint]] = (("↵", "确定", "submit"), ("esc", "取消", "cancel"))

    def __init__(
        self,
        title: str,
        value: str = "",
        *,
        placeholder: str = "",
        password: bool = False,
        note: str = "",
        validate: Callable[[str], str | None] | None = None,
        info: Callable[[str], str] | None = None,
        input_id: str = "popup-input",
    ) -> None:
        super().__init__(title)
        self.info = info
        self.value = value
        self.placeholder = placeholder
        self.password = password
        self.note = note
        self.validate = validate
        self.input_id = input_id

    def compose(self) -> ComposeResult:
        yield self.frame(
            Input(
                value=self.value,
                placeholder=self.placeholder,
                password=self.password,
                id=self.input_id,
                classes="popup-input",
            ),
            Static(self.note, id="popup-note", classes="popup-note"),
        )

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one(Input).focus()
        self._check(self.value)

    def _check(self, value: str) -> str | None:
        error = self.validate(value) if self.validate else None
        colors = ui.palette(self.app)
        note = self.query_one("#popup-note", Static)
        message = self.info(value) if self.info and not error else self.note
        if error:
            note.update(Text(error, style=colors.danger))
        else:
            note.update(Text(message, style=colors.muted))
        note.display = bool(error or message)
        return error

    @on(Input.Changed)
    def changed(self, event: Input.Changed) -> None:
        self._check(event.value)

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_submit()

    def action_submit(self) -> None:
        value = self.query_one(Input).value
        if self._check(value) is None:
            self.dismiss(value)


class MenuPopup(Popup):
    """从若干选项中选一个（单击即选）；当前值前显示 ●。"""

    HINTS: ClassVar[Sequence[Hint]] = (("↵", "确定", "choose"), ("←", "返回", "cancel"))

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消", priority=True),
        Binding("left,h", "back", "返回", show=False),
        Binding("right,l", "choose", "确定", show=False),
        Binding("j", "cursor_down", "下移", show=False),
        Binding("k", "cursor_up", "上移", show=False),
    ]

    def __init__(
        self, title: str, options: Sequence[tuple[str, str]], current: str = "", note: str = ""
    ) -> None:
        super().__init__(title)
        self.options = list(options)
        self.current = current
        self.note = note

    def compose(self) -> ComposeResult:
        items = [ListItem(Label(name)) for name, _ in self.options]
        children: list[Any] = [ListView(*items, id="popup-menu")]
        if self.note:
            children.append(Static(self.note, classes="popup-note"))
        yield self.frame(*children)

    def on_mount(self) -> None:
        super().on_mount()
        colors = ui.palette(self.app)
        view = self.query_one("#popup-menu", ListView)
        for item, (name, value) in zip(view.children, self.options):
            text = Text("● " if value == self.current else "  ", style=colors.accent)
            text.append_text(self.option_text(name, value, colors))
            item.query_one(Label).update(text)
        values = [value for _, value in self.options]
        view.index = values.index(self.current) if self.current in values else 0
        view.styles.height = len(self.options)
        view.focus()

    def option_text(self, name: str, value: str, colors: ui.Palette) -> Text:
        """选项文字；子类可按取值着色。"""
        return Text(name, style=colors.fg)

    def action_cursor_down(self) -> None:
        self.query_one("#popup-menu", ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#popup-menu", ListView).action_cursor_up()

    @on(ListView.Selected)
    def selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.dismiss(self.options[event.list_view.index or 0][1])

    def select(self, value: str) -> None:
        values = [item for _, item in self.options]
        self.query_one("#popup-menu", ListView).index = values.index(value)

    def action_choose(self) -> None:
        self.dismiss(self.options[self.query_one("#popup-menu", ListView).index or 0][1])


class ChoiceNotePopup(MenuPopup):
    """选项 + 备注：j/k 选择，tab 切到备注，enter 保存。返回 (值, 备注)。"""

    ICON = "mark"
    HINTS: ClassVar[Sequence[Hint]] = (
        ("↵", "保存", "save"),
        ("tab", "备注", "toggle_focus"),
        ("←", "返回", "cancel"),
    )

    BINDINGS: ClassVar[list[Binding]] = [
        *MenuPopup.BINDINGS,
        Binding("tab", "toggle_focus", "备注", priority=True),
    ]

    def __init__(
        self, title: str, options: Sequence[tuple[str, str]], current: str = "", note: str = ""
    ) -> None:
        super().__init__(title, options, current)
        self.initial_note = note

    def compose(self) -> ComposeResult:
        items = [ListItem(Label(name)) for name, _ in self.options]
        yield self.frame(
            ListView(*items, id="popup-menu"),
            Input(
                value=self.initial_note,
                placeholder="备注（可选）",
                id="note",
                classes="popup-input",
            ),
        )

    def action_toggle_focus(self) -> None:
        note = self.query_one("#note", Input)
        if self.focused is note:
            self.query_one("#popup-menu", ListView).focus()
        else:
            note.focus()

    def _result(self) -> tuple[str, str]:
        index = self.query_one("#popup-menu", ListView).index or 0
        return self.options[index][1], self.query_one("#note", Input).value

    @on(ListView.Selected)
    def selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.dismiss(self._result())

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(self._result())

    def save(self) -> None:
        self.dismiss(self._result())

    def action_save(self) -> None:
        self.save()

    def action_choose(self) -> None:
        self.save()


class ConfirmPopup(Popup):
    """是 / 否确认：「是」在左、「否」在右，←/→（h/l、Tab）移动选中项，Enter 确定；
    y / n 直接回答，Esc 等同于否。初始选中 default 一侧（默认是安全的「否」）。"""

    ICON = "warning"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,n", "answer(False)", "否", priority=True),
        Binding("y", "answer(True)", "是", priority=True),
        Binding("left,h", "choose(True)", "选「是」", priority=True),
        Binding("right,l", "choose(False)", "选「否」", priority=True),
        Binding("tab,shift+tab", "toggle_choice", "切换", priority=True),
        Binding("enter,space", "answer_default", "确定", priority=True),
    ]

    def __init__(self, title: str, message: str, *, default: bool = False) -> None:
        super().__init__(title, [("y", "是", "answer(True)"), ("n", "否", "answer(False)")])
        self.message = message
        self.default = default
        self.choice = default

    def compose(self) -> ComposeResult:
        yield self.frame(Static(self.message, classes="popup-message"))

    def on_mount(self) -> None:
        super().on_mount()
        self._show_choice()

    def _show_choice(self) -> None:
        self.query_one(HintRow).show(self.hints, 0 if self.choice else 1)

    def action_choose(self, value: bool) -> None:
        self.choice = value
        self._show_choice()

    def action_toggle_choice(self) -> None:
        self.action_choose(not self.choice)

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)

    def action_answer_default(self) -> None:
        """Enter：确定当前选中项（未移动时即 default）。"""
        self.dismiss(self.choice)

    def action_cancel(self) -> None:
        self.dismiss(False)


class SearchLine(ModalScreen[str | None]):
    """nvim 风格：屏幕底部一行 /，边输入边跳到第一处匹配；enter 保留位置，esc 取消。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消", priority=True),
    ]
    DEFAULT_CSS = """
    SearchLine { align: left bottom; background: transparent; }
    SearchLine > #search-line { dock: bottom; height: 1; width: 100%; background: $surface; }
    SearchLine Input { border: none; height: 1; padding: 0; background: $surface; width: 1fr; }
    SearchLine Label { width: 2; color: $primary; text-style: bold; }
    """

    def __init__(self, on_change: Callable[[str], bool] | None = None) -> None:
        super().__init__()
        self.on_change = on_change

    def compose(self) -> ComposeResult:
        from textual.containers import Horizontal

        yield Horizontal(Label("/"), Input(id="search-text"), id="search-line")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Changed)
    def changed(self, event: Input.Changed) -> None:
        if self.on_change is not None and event.value:
            found = self.on_change(event.value)
            event.input.styles.color = None if found else "red"

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        if event.widget is self:
            self.dismiss(None)
