"""
Module: TUI / input interaction
Description: 区分列表单击选中、双击打开与回车激活。
Scope: TUI
Notes: 不修改任何业务层、采集或检测逻辑。
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import RenderableType
from textual import events
from textual.message import Message
from textual.widgets import ListItem, ListView


class NavigateListView(ListView):
    """单击只移动高亮；键盘 Enter 和双击才发布独立激活消息。"""

    class Activated(Message):
        """keyboard=True 表示由回车触发（页面可以把回车解释为复核），否则是双击打开。"""

        def __init__(self, index: int, keyboard: bool = False) -> None:
            super().__init__()
            self.index = index
            self.keyboard = keyboard

    def action_select_cursor(self) -> None:
        if self.index is not None and self.highlighted_child is not None:
            self.post_message(self.Activated(self.index, keyboard=True))

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


def __getattr__(name: str):
    # 旧名称兼容：搜索改为底部 / 行。
    if name == "SearchDialog":
        from ojaudit.tui.popup import SearchLine

        return SearchLine
    raise AttributeError(name)


def refill(
    view: ListView,
    rows: Sequence[RenderableType],
    *,
    index: int | None = None,
    classes: Sequence[str] | None = None,
) -> None:
    """原地重填列表：更新已有条目的文字，多则追加、少则移除，不整表清空重建。

    clear() 后旧条目要到下一帧才真正移除，期间设置选中会把高亮打在旧条目上（高亮消失）；
    原地更新时条目始终是同一批，选中与高亮自然保持。index 为 None 时保留当前选中位置。
    classes 为每行附加的 CSS 类（如设置页的分组标题 section），空串表示无。
    """
    from textual.widgets import Label

    items = [child for child in view.children if not child.has_class("-gone")]
    for position, row in enumerate(rows):
        if position < len(items):
            item = items[position]
            # 同一帧刚追加的条目尚未挂载，查不到子控件，所以创建时记下标签。
            label = getattr(item, "row_label", None) or item.query_one(Label)
            label.update(row)
        else:
            label = Label(row)
            item = NavigateListItem(label)
            item.row_label = label  # type: ignore[attr-defined]
            view.append(item)
        wanted = classes[position] if classes else ""
        item.set_class(wanted == "section", "section")
    for extra in items[len(rows) :]:
        extra.add_class("-gone")
        extra.remove()
    if not rows:
        view.index = None
        return
    target = index if index is not None else view.index
    target = 0 if target is None else max(0, min(target, len(rows) - 1))
    if view.index != target:
        view.index = target
