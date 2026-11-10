"""
Module: TUI / app
Description: 组装 Textual 应用、全局按键与界面样式。
Scope: TUI
Notes: 独立入口，不改变现有 CLI 的行为。
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App

from ojaudit.core.config import data_dir, load_config
from ojaudit.tui.data import LocalContests
from ojaudit.tui.icons import label
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
        ("t", "cycle_theme", "切换主题"),
    ]
    THEMES: ClassVar[tuple[str, ...]] = ("ansi", "catppuccin", "nord", "gruvbox")
    THEME_IDS: ClassVar[dict[str, str]] = {
        "catppuccin": "catppuccin-mocha",
        "nord": "nord",
        "gruvbox": "gruvbox",
    }
    theme_name = "ansi"

    def __init__(
        self, contests: LocalContests | None = None, db_path: str | Path | None = None
    ) -> None:
        super().__init__()
        settings = load_config().get("storage", {})
        configured = settings.get("sqlite_path") if isinstance(settings, dict) else None
        selected = db_path or (
            Path(configured).expanduser() if configured else data_dir() / "ojaudit.sqlite"
        )
        self.contests = contests if contests is not None else LocalContests(selected)
        appearance = load_config().get("appearance", {})
        self.theme_name = str(appearance.get("theme", "ansi"))
        self.nerd_font = bool(appearance.get("nerd_font", False))

    def on_mount(self) -> None:
        self._apply_theme()
        self.push_screen(HomeScreen())

    def _apply_theme(self) -> None:
        name = self.THEME_IDS.get(self.theme_name)
        if name is not None and name in self.available_themes:
            self.theme = name
        elif "textual-ansi" in self.available_themes:
            self.theme = "textual-ansi"

    def action_cycle_theme(self) -> None:
        index = self.THEMES.index(self.theme_name) if self.theme_name in self.THEMES else 0
        self.theme_name = self.THEMES[(index + 1) % len(self.THEMES)]
        self._apply_theme()
        self.notify(label("theme", f"主题：{self.theme_name}（设置页可保存）", self.nerd_font))

    def action_help(self) -> None:
        self.notify(
            label(
                "help",
                "j/k 移动 · g/G 首尾 · Enter/l 进入 · Esc/h 返回 · a 全部 · t 主题 · q 退出",
                self.nerd_font,
            )
        )


def main(db_path: str | Path | None = None) -> None:
    AuditApp(db_path=db_path).run()


if __name__ == "__main__":
    main()
