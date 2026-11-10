"""
Module: TUI / splitter
Description: 两栏之间不可见的拖拽区：按住拖动调整左栏宽度，双击恢复默认，宽度按名称记入配置。
Scope: TUI
Notes: 只调整左侧目标栏的宽度，右侧栏用 1fr 自动填满。
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.widget import Widget


def saved_width(name: str) -> int | None:
    from ojaudit.core.config import load_config

    layout = load_config().get("layout", {})
    value = layout.get(name) if isinstance(layout, dict) else None
    return value if isinstance(value, int) and value > 0 else None


def save_width(name: str, width: int | None) -> None:
    from ojaudit.core.config import load_config, save_config

    config = load_config()
    layout = config.setdefault("layout", {})
    if not isinstance(layout, dict):
        layout = config["layout"] = {}
    if width is None:
        layout.pop(name, None)
    else:
        layout[name] = width
    save_config(config)


class Splitter(Widget):
    """竖直分隔条：拖动改变 target 的宽度。"""

    DEFAULT_CSS = """
    Splitter { width: 1; height: 1fr; }
    """

    def __init__(self, target: str, name: str, *, minimum: int = 12, keep_right: int = 20) -> None:
        super().__init__(name=name)
        self.target = target
        self.minimum = minimum
        self.keep_right = keep_right
        self.dragging = False

    def on_mount(self) -> None:
        width = saved_width(self.name or "")
        if width is not None:
            self.call_after_refresh(self._apply, width)

    def _target(self) -> Widget:
        return self.parent.query_one(f"#{self.target}")  # type: ignore[union-attr]

    def _apply(self, width: int) -> int:
        parent = self.parent
        total = parent.size.width if isinstance(parent, Widget) else width
        width = max(self.minimum, min(width, total - self.keep_right - 1))
        self._target().styles.width = width
        return width

    def render(self) -> Text:
        # 不画分隔线：拖动两栏之间的空隙即可调整宽度（与 nvim / lazygit 一致）。
        return Text("")

    def on_click(self, event: events.Click) -> None:
        if event.chain >= 2:
            self._target().styles.width = None
            save_width(self.name or "", None)

    def on_mouse_down(self, _event: events.MouseDown) -> None:
        self.dragging = True
        self.capture_mouse()
        self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self.dragging:
            self._apply(event.screen_x - self._target().region.x)

    def on_mouse_up(self, _event: events.MouseUp) -> None:
        if not self.dragging:
            return
        self.dragging = False
        self.release_mouse()
        self.refresh()
        width = self._target().styles.width
        if width is not None:
            save_width(self.name or "", int(width.value))
