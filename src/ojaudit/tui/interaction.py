"""
Module: TUI / input interaction
Description: 区分列表单击选中、双击打开与回车激活；长列表按需分批挂载。
Scope: TUI
Notes:
- 不修改任何业务层、采集或检测逻辑。
- 每一行是一个控件，一次挂载上千行要一秒以上（主要是套用样式）。refill 只先挂载前 CHUNK 行，
  选中或滚动接近末尾时再追加下一批；搜索、跳到末尾前调用 load_all() 挂载全部。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from rich.console import RenderableType
from textual import events
from textual.message import Message
from textual.widgets import ListItem, ListView

CHUNK = 200  # 每批挂载的行数
_MARGIN = 30  # 选中或滚动距已挂载末尾不足这么多行时追加下一批


class LazyRows(Sequence[RenderableType]):
    """按需渲染的行：只有真正挂载的行才调用 render；切片仍是按需的视图。"""

    def __init__(self, count: int, render: Callable[[int], RenderableType], start: int = 0) -> None:
        self.count = max(count, 0)
        self.render = render
        self.start = start

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, slice):
            begin, end, step = index.indices(self.count)
            if step != 1:
                return [self[i] for i in range(begin, end, step)]
            return LazyRows(end - begin, self.render, self.start + begin)
        if not -self.count <= index < self.count:
            raise IndexError(index)
        return self.render(self.start + index % self.count)


class NavigateListView(ListView):
    """单击只移动高亮；键盘 Enter 和双击才发布独立激活消息；未挂载的行按需追加。"""

    def __init__(self, *children: Any, **kwargs: Any) -> None:
        super().__init__(*children, **kwargs)
        self.pending: Sequence[RenderableType] = []
        self.pending_classes: Sequence[str] = []
        # 刚追加的行要到下一帧才排版，期间滚动范围还是旧值，不能据此再追加。
        self._just_grew = False

    def mounted_count(self) -> int:
        return sum(1 for child in self.children if not child.has_class("-gone"))

    def grow(self, count: int = CHUNK) -> None:
        """再挂载 count 行（来自上次 refill 留下的待挂载行）。"""
        if not self.pending:
            return
        self._just_grew = True
        self.call_after_refresh(setattr, self, "_just_grew", False)
        rows, self.pending = self.pending[:count], self.pending[count:]
        classes = list(self.pending_classes[:count])
        self.pending_classes = self.pending_classes[count:]
        for position, row in enumerate(rows):
            self.append(_item(row, classes[position] if position < len(classes) else ""))

    def load_all(self) -> None:
        self.grow(len(self.pending))

    def watch_index(self, old_index: int | None, new_index: int | None) -> None:
        super().watch_index(old_index, new_index)
        if new_index is not None and new_index >= self.mounted_count() - _MARGIN:
            self.grow()

    def watch_scroll_y(self, old: float, new: float) -> None:
        super().watch_scroll_y(old, new)
        if self.pending and not self._just_grew and new >= self.max_scroll_y - _MARGIN:
            self.grow()

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


def _item(row: RenderableType, css: str) -> NavigateListItem:
    from textual.widgets import Label

    label = Label(row)
    item = NavigateListItem(label)
    item.row_label = label  # type: ignore[attr-defined]
    item.set_class(css == "section", "section")
    return item


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
    rows 可以是 LazyRows：NavigateListView 只先挂载（并渲染）需要的前几批，其余按需追加。
    """
    from textual.widgets import Label

    items = [child for child in view.children if not child.has_class("-gone")]
    target = index if index is not None else view.index
    if isinstance(view, NavigateListView):
        shown = max(CHUNK, len(items), (target or 0) + _MARGIN + 1)
        view.pending = rows[shown:] if len(rows) > shown else []
        view.pending_classes = list(classes[shown:]) if classes else []
        rows = rows[:shown]
    for position, row in enumerate(rows):
        if position < len(items):
            item = items[position]
            # 同一帧刚追加的条目尚未挂载，查不到子控件，所以创建时记下标签。
            label = getattr(item, "row_label", None) or item.query_one(Label)
            label.update(row)
        else:
            item = _item(row, "")
            view.append(item)
        wanted = classes[position] if classes else ""
        item.set_class(wanted == "section", "section")
    for extra in items[len(rows) :]:
        extra.add_class("-gone")
        extra.remove()
    if not rows:
        view.index = None
        return
    target = 0 if target is None else max(0, min(target, len(rows) - 1))
    if view.index != target:
        view.index = target
