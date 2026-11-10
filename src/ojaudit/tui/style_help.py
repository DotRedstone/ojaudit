"""
Module: TUI / style help
Description: 帮助弹窗：根据当前页面的按键绑定自动列出全部操作。
Scope: TUI
"""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import ModalScreen, Screen
from textual.widgets import Static

from ojaudit.tui import ui

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


class StyleHelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "close", "返回"),
        ("question_mark", "close", "关闭帮助"),
    ]
    DEFAULT_CSS = """
    StyleHelpScreen { align: center middle; background: $background 60%; }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="style-help", classes="dialog")

    def on_mount(self) -> None:
        colors = ui.palette(self.app)
        stack = self.app.screen_stack
        page = stack[-2] if len(stack) > 1 else None
        title = getattr(page, "TITLE", "") or "当前页面"
        text = Text(f"{title} · 按键\n\n", style=f"bold {colors.fg}")
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
