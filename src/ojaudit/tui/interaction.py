"""
Module: TUI / input interaction
Description: 区分列表单击选中和双击激活，并提供搜索及可点击面包屑。
Scope: TUI
Notes: 不修改任何业务层、采集或检测逻辑。
"""

from __future__ import annotations

from typing import Any

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
    """顶栏：点击左侧路径返回上一级；后台任务运行时点击右侧状态可取消任务。"""

    job_x = 10**6

    def on_click(self, event: events.Click) -> None:
        event.stop()
        app: Any = self.app
        if event.x >= self.job_x:
            if getattr(app, "job_running", False):
                from ojaudit.tui.popup import ConfirmPopup

                app.push_screen(
                    ConfirmPopup("后台任务", f"{app.job_status}\n取消这个任务？"),
                    lambda ok: ok and app.cancel_workflow(),
                )
            return
        back = getattr(self.screen, "action_back", None)
        if callable(back):
            back()


def __getattr__(name: str):
    # 旧名称兼容：搜索改为底部 / 行。
    if name == "SearchDialog":
        from ojaudit.tui.popup import SearchLine

        return SearchLine
    raise AttributeError(name)
