"""
Module: TUI / app
Description: 组装 Textual 应用、全局按键与界面样式。
Scope: TUI
Notes: 独立入口，不改变现有 CLI 的行为。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import App

from ojaudit.core.config import data_dir, load_config
from ojaudit.tui.data import LocalContests
from ojaudit.tui.rice_theme import load_wallpaper_theme, wallpaper_signature
from ojaudit.tui.screens import HomeScreen


class AuditApp(App[None]):
    TITLE = "ojaudit · 审核工作台"
    CSS_PATH = "themes/nowcoder.tcss"
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "退出"),
        ("question_mark", "help", "帮助"),
        ("t", "cycle_theme", "切换主题"),
    ]
    THEMES: ClassVar[tuple[str, ...]] = (
        "auto",
        "wallpaper",
        "ansi-dark",
        "catppuccin-mocha",
        "nord",
        "gruvbox",
        "textual-dark",
    )
    THEME_IDS: ClassVar[dict[str, str]] = {
        "catppuccin": "catppuccin-mocha",
        "ansi": "ansi-dark",
        "ansi-dark": "textual-dark",
    }
    theme_name = "auto"

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
        self.theme_name = str(appearance.get("theme", "auto"))
        self.nerd_font = bool(appearance.get("nerd_font", False))
        self.key_hints = bool(appearance.get("key_hints", True))
        self.wallpaper_source = ""
        self.wallpaper_signature: tuple[int, int] | None = None

    def on_mount(self) -> None:
        self._apply_theme()
        self.push_screen(HomeScreen())
        self.set_interval(4, self.poll_wallpaper)

    def _fallback_theme(self) -> str:
        if "catppuccin-mocha" in self.available_themes:
            return "catppuccin-mocha"
        return "textual-dark"

    def _apply_theme(self) -> None:
        choice = self.THEME_IDS.get(self.theme_name, self.theme_name)
        if choice in ("auto", "wallpaper"):
            wallpaper, path = load_wallpaper_theme()
            if wallpaper is not None:
                self.register_theme(wallpaper)
                self.wallpaper_source = path
                self.wallpaper_signature = wallpaper_signature(path)
                self.theme = "wallpaper"
                return
            self.wallpaper_source = ""
            self.wallpaper_signature = None
            choice = self._fallback_theme()
        elif choice not in self.available_themes:
            choice = self._fallback_theme()
        self.theme = choice

    def poll_wallpaper(self) -> None:
        if self.theme_name not in ("auto", "wallpaper"):
            return
        wallpaper, path = load_wallpaper_theme()
        signature = wallpaper_signature(path) if path else None
        if path == self.wallpaper_source and signature == self.wallpaper_signature:
            return
        if wallpaper is None:
            self.wallpaper_source = ""
            self.wallpaper_signature = None
            self.theme = self._fallback_theme()
            return
        self.register_theme(wallpaper)
        self.wallpaper_source = path
        self.wallpaper_signature = signature
        if self.theme == "wallpaper":
            self.theme = self._fallback_theme()
        self.theme = "wallpaper"

    def status_line(self, current: str, contest_id: str = "—") -> Text:
        colors = self.current_theme
        mode_color = str(colors.success or "#a3be8c")
        background = str(colors.background or "#1e1e2e")
        bar = Text()
        bar.append(" NORMAL ", style=f"bold {background} on {mode_color}")
        bar.append(" " if self.nerd_font else "▌ ", style=mode_color)
        bar.append(f"#{contest_id} › {current}", style="bold")
        right = f"{self.theme_name} · {datetime.now():%H:%M}"
        gap = max(1, self.size.width - bar.cell_len - Text(right).cell_len - 2)
        bar.append(" " * gap)
        bar.append(right, style="dim")
        return bar

    def action_cycle_theme(self) -> None:
        index = self.THEMES.index(self.theme_name) if self.theme_name in self.THEMES else 0
        self.theme_name = self.THEMES[(index + 1) % len(self.THEMES)]
        self._apply_theme()
        self.notify(f"主题：{self.theme_name}（设置页可保存）")

    def action_help(self) -> None:
        from ojaudit.tui.style_help import StyleHelpScreen

        self.push_screen(StyleHelpScreen())


def main(db_path: str | Path | None = None) -> None:
    AuditApp(db_path=db_path).run()


if __name__ == "__main__":
    main()
