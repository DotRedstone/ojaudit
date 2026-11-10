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
        ("escape,h,q", "close", "返回"),
        ("question_mark", "close", "关闭帮助"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(
            "ojaudit › 帮助\n\n"
            "↑↓/j/k 移动 · ←/h/Esc 返回 · →/l/Enter/空格 进入\n"
            "鼠标单击选中 · 双击进入 · / 搜索 · g/G 首尾\n"
            "a 切换全部比赛 · t 切换主题 · q 子页返回（首页退出） · ? 帮助\n\n"
            "更多操作请参阅 docs/tui.md\n\nEsc 返回",
            id="style-help",
            classes="dialog-box",
        )

    def action_close(self) -> None:
        self.dismiss()
