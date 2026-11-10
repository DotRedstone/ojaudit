"""
Module: TUI / style help
Description: Rounded help modal for current navigation commands.
Scope: TUI
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static


class StyleHelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "close", "返回"),
        ("question_mark", "close", "关闭帮助"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(
            "ojaudit › 帮助\n\n"
            "j/k 上下 · g/G 首尾 · Enter/l 进入 · Esc/h 返回\n"
            "a 显示全部比赛 · t 切换主题 · q 退出 · ? 帮助\n\n"
            "更多操作请参阅 docs/tui.md\n\nEsc 返回",
            id="style-help",
        )

    def action_close(self) -> None:
        self.dismiss()
