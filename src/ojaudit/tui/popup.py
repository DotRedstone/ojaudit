"""
Module: TUI / popup
Description: lazygit 风格的弹窗：标题写在边框上、操作提示写在下边框，无按钮、无遮罩；
    以及 nvim 风格的底部 / 搜索行。
Scope: TUI
Notes:
- 所有弹窗 Esc 取消、Enter 确认；输入类弹窗可带实时校验，校验不通过时 Enter 不会关闭。
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


def hint(*pairs: tuple[str, str]) -> str:
    return "  ".join(f"{key} {action}" for key, action in pairs)


class Popup(ModalScreen[Any]):
    """弹窗基类：居中、透明背景、单层圆角边框。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消", priority=True),
    ]
    DEFAULT_CSS = """
    Popup { align: center middle; background: transparent; }
    """
    WIDTH = 64
    ICON = "open"

    def __init__(self, title: str, footer: str = "") -> None:
        super().__init__()
        self.popup_title = title
        self.popup_footer = footer

    def frame(self, *children: Any, id: str | None = None) -> Vertical:
        box = Vertical(*children, id=id, classes="popup dialog")
        box.styles.width = self.WIDTH
        return box

    def on_mount(self) -> None:
        box = self.query_one(".popup")
        box.border_title = f" {label(self.ICON, self.popup_title, self.app.nerd_font)} "
        box.border_subtitle = f" {self.popup_footer} " if self.popup_footer else ""

    def action_cancel(self) -> None:
        self.dismiss(None)


class InputPopup(Popup):
    """单行输入。validate 返回错误文字或 None；note 显示在输入框下方的说明。"""

    def __init__(
        self,
        title: str,
        value: str = "",
        *,
        placeholder: str = "",
        password: bool = False,
        note: str = "",
        validate: Callable[[str], str | None] | None = None,
        input_id: str = "popup-input",
    ) -> None:
        super().__init__(title, hint(("enter", "确定"), ("esc", "取消")))
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
        if error:
            note.update(Text(error, style=colors.danger))
        else:
            note.update(Text(self.note, style=colors.muted))
        note.display = bool(error or self.note)
        return error

    @on(Input.Changed)
    def changed(self, event: Input.Changed) -> None:
        self._check(event.value)

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self._check(event.value) is None:
            self.dismiss(event.value)


class MenuPopup(Popup):
    """从若干选项中选一个；当前值前显示 ●。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消", priority=True),
        Binding("j", "cursor_down", "下移", show=False),
        Binding("k", "cursor_up", "上移", show=False),
    ]

    def __init__(
        self, title: str, options: Sequence[tuple[str, str]], current: str = "", note: str = ""
    ) -> None:
        super().__init__(title, hint(("j/k", "选择"), ("enter", "确定"), ("esc", "取消")))
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
            text.append(name, style=colors.fg)
            item.query_one(Label).update(text)
        values = [value for _, value in self.options]
        view.index = values.index(self.current) if self.current in values else 0
        view.styles.height = len(self.options)
        view.focus()

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


class ChoiceNotePopup(MenuPopup):
    """选项 + 备注：j/k 选择，tab 切到备注，enter 保存。返回 (值, 备注)。"""

    ICON = "mark"

    BINDINGS: ClassVar[list[Binding]] = [
        *MenuPopup.BINDINGS,
        Binding("tab", "toggle_focus", "备注", priority=True),
    ]

    def __init__(
        self, title: str, options: Sequence[tuple[str, str]], current: str = "", note: str = ""
    ) -> None:
        super().__init__(title, options, current)
        self.popup_footer = hint(
            ("j/k", "选择"), ("tab", "备注"), ("enter", "保存"), ("esc", "取消")
        )
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


class ConfirmPopup(Popup):
    """是 / 否确认。默认（enter）为 safe 一侧；y 选是，n / esc 选否。"""

    ICON = "warning"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,n", "answer(False)", "否", priority=True),
        Binding("y", "answer(True)", "是", priority=True),
        Binding("enter", "answer_default", "默认", priority=True),
    ]

    def __init__(self, title: str, message: str, *, default: bool = False) -> None:
        footer = hint(("y", "是"), ("n", "否"), ("enter", "是" if default else "否"))
        super().__init__(title, footer)
        self.message = message
        self.default = default

    def compose(self) -> ComposeResult:
        yield self.frame(Static(self.message, classes="popup-message"))

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)

    def action_answer_default(self) -> None:
        self.dismiss(self.default)

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
