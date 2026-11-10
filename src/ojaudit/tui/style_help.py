"""
Module: TUI / style help
Description: 帮助弹窗：根据当前页面的按键绑定自动列出全部操作。
Scope: TUI
"""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static

from ojaudit.tui import ui
from ojaudit.tui.icons import label
from ojaudit.tui.popup import Popup

KEY_NAMES = {
    "escape": "esc",
    "enter": "↵",
    "space": "space",
    "left": "←",
    "right": "→",
    "up": "↑",
    "down": "↓",
    "slash": "/",
    "question_mark": "?",
    "left_square_bracket": "[",
    "right_square_bracket": "]",
    "shift+g": "G",
    "shift+tab": "⇧tab",
    "shift+left": "⇧←",
    "ctrl+s": "ctrl+s",
}
GLOBAL = (("?", "帮助"), ("t", "切换主题"), ("q", "返回（首页退出）"))


def _bindings(screen: Screen) -> list[tuple[str, str]]:
    """合并同一动作的多个按键，保持声明顺序。"""
    merged: dict[str, tuple[list[str], str]] = {}
    for binding in getattr(screen, "BINDINGS", []):
        keys, action, description = (
            (binding.key, binding.action, binding.description)
            if hasattr(binding, "key")
            else binding
        )
        names = [KEY_NAMES.get(key.strip(), key.strip()) for key in keys.split(",")]
        entry = merged.setdefault(action, ([], description))
        entry[0].extend(name for name in names if name not in entry[0])
    return [(" ".join(keys), description) for keys, description in merged.values()]


class StyleHelpScreen(Popup):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,q", "close", "返回"),
        ("question_mark", "close", "关闭帮助"),
    ]
    WIDTH = 72
    ICON = "help"
    ACTIONS = (("关闭", "close"),)

    def __init__(self) -> None:
        super().__init__("按键", "esc 关闭")

    def compose(self) -> ComposeResult:
        yield self.frame(Static("", id="style-help"))

    def on_mount(self) -> None:
        super().on_mount()
        colors = ui.palette(self.app)
        stack = self.app.screen_stack
        page = stack[-2] if len(stack) > 1 else None
        title = getattr(page, "TITLE", "") or "当前页面"
        self.query_one(
            ".popup"
        ).border_title = f" {label('help', f'{title} · 按键', self.app.nerd_font)} "
        text = Text()
        rows = _bindings(page) if page is not None else []
        for keys, description in [*rows, ("", ""), *GLOBAL]:
            if not keys:
                text.append("\n")
                continue
            text.append_text(ui.fit(Text(keys, style=f"bold {colors.accent}"), 22))
            text.append(description + "\n", style=colors.fg)
        text.append("\n鼠标：单击选中 · 双击打开 · 点击顶栏返回上一级", style=colors.muted)
        self.query_one("#style-help", Static).update(text)

    def action_close(self) -> None:
        self.dismiss()
