"""
Module: TUI / input interaction
Description: 区分列表单击选中和双击激活，并提供搜索及可点击面包屑。
Scope: TUI
Notes: 不修改任何业务层、采集或检测逻辑。
"""

from __future__ import annotations

from typing import ClassVar

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static


class NavigateListView(ListView):
    """单击只移动高亮；键盘 Enter 和双击才发布独立激活消息。"""

    class Activated(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def action_select_cursor(self) -> None:
        if self.index is not None and self.highlighted_child is not None:
            self.post_message(self.Activated(self.index))

    def _on_list_item__child_clicked(self, event: ListItem._ChildClicked) -> None:
        event.stop()
        self.focus()
        self.index = list(self.children).index(event.item)


class NavigateListItem(ListItem):
    """单击仅更改高亮；双击才发出 ListView.Selected。"""

    def _on_click(self, event: events.Click) -> None:
        view = self.parent
        if not isinstance(view, ListView):
            return
        view.focus()
        view.index = list(view.children).index(self)
        if event.chain >= 2:
            view.post_message(NavigateListView.Activated(view.index))
        event.stop()


class Breadcrumb(Static):
    """单击当前面包屑回到上一级 Screen。"""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        back = getattr(self.screen, "action_back", None)
        if callable(back):
            back()


class SearchDialog(ModalScreen[str | None]):
    """当前列表的轻量文本搜索；Esc 永远可取消。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消搜索", priority=True),
    ]
    CSS = """
    SearchDialog { align: center middle; }
    #search-dialog { width: 64; height: auto; padding: 1 2;
                     border: round $accent; background: $panel; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="search-dialog"):
            yield Label("搜索当前列表（输入部分文字）")
            yield Input(placeholder="搜索…", id="search-text")
            with Horizontal():
                yield Button("查找", id="search-confirm", variant="primary")
                yield Button("取消", id="search-cancel")

    def on_mount(self) -> None:
        self.query_one("#search-text", Input).focus()

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(
            self.query_one("#search-text", Input).value
            if event.button.id == "search-confirm"
            else None
        )

    def action_cancel(self) -> None:
        self.dismiss(None)
