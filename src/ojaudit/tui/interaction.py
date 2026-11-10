"""
Module: TUI / input interaction
Description: 区分列表单击选中和双击激活，并提供搜索及可点击面包屑。
Scope: TUI
Notes: 不修改任何业务层、采集或检测逻辑。
"""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import ListItem, ListView, Static


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
    """顶栏：单击回到上一级 Screen。"""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        back = getattr(self.screen, "action_back", None)
        if callable(back):
            back()


def __getattr__(name: str):
    # 旧名称兼容：搜索改为底部 / 行。
    if name == "SearchDialog":
        from ojaudit.tui.popup import SearchLine

        return SearchLine
    raise AttributeError(name)
