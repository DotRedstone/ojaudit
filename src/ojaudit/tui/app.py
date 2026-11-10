"""
Module: TUI / app
Description: 组装 Textual 应用、全局按键与界面样式。
Scope: TUI
Notes: 独立入口，不改变现有 CLI 的行为。
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App

from ojaudit.tui.data import LocalContests
from ojaudit.tui.screens import HomeScreen


class AuditApp(App[None]):
    CSS = """
    Screen { layout: vertical; background: $surface; }
    #breadcrumb { height: 3; padding: 1 2; background: $panel; color: $text; }
    #pane { height: 1fr; margin: 1 2; border: round $panel; border-title-color: $accent; }
    #pane:focus-within { border: round $accent; }
    .pane-title { height: 3; padding: 1 2; text-style: bold; color: $accent; }
    #summary { height: 3; padding: 1 2; }
    ListView { height: 1fr; border: none; }
    ListItem { padding: 0 2; }
    ListItem.--highlight { background: $accent; color: $background; text-style: bold; }
    #status { dock: bottom; height: 1; background: $primary; color: $background; text-style: bold; }
    #evidence-meta { height: 6; padding: 0 1; }
    #code-pair { height: 1fr; }
    .source-pane { width: 1fr; height: 1fr; margin: 0 1; border: round $panel;
                   overflow: auto; padding: 0 1; }
    .source-pane:focus { border: round $accent; }
    #code-meta { height: 3; padding: 0 1; }
    #code-body { height: 1fr; overflow: auto; padding: 0 1; }
    #settings-columns { min-height: 12; }
    #ranking-note { height: 2; padding: 0 1; color: $warning; }
    """
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "退出"),
        ("question_mark", "help", "帮助"),
    ]
    theme_name = "终端默认"

    def __init__(self, contests: LocalContests | None = None) -> None:
        super().__init__()
        self.contests = contests if contests is not None else LocalContests()

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())

    def action_help(self) -> None:
        self.notify("j/k 移动 · g/G 首尾 · Enter/l 进入 · Esc/h 返回 · a 全部 · q 退出")


def main() -> None:
    AuditApp().run()


if __name__ == "__main__":
    main()
