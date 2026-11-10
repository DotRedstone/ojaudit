"""
Module: TUI / app
Description: 组装 Textual 应用、全局按键与界面样式。
Scope: TUI
Notes: 独立入口，不改变现有 CLI 的行为。
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from threading import Event
from typing import Any, ClassVar

from textual.app import App

from ojaudit.core.config import config_dir, data_dir, load_config
from ojaudit.tui.data import LocalContests
from ojaudit.tui.icons import label
from ojaudit.tui.rice_theme import load_wallpaper_theme, wallpaper_signature
from ojaudit.tui.screens import HomeScreen
from ojaudit.tui.workflow import analyze_local, persist_bundle


class AuditApp(App[None]):
    TITLE = "ojaudit · 审核工作台"
    CSS_PATH = "themes/nowcoder.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "context_quit", "返回/退出"),
        ("question_mark", "help", "帮助"),
        ("t", "cycle_theme", "切换主题"),
    ]
    theme_name = "auto"

    def __init__(
        self,
        contests: LocalContests | None = None,
        db_path: str | Path | None = None,
        *,
        auto_sync: bool = False,
    ) -> None:
        super().__init__()
        self.auto_sync = auto_sync
        settings = load_config().get("storage", {})
        configured = settings.get("sqlite_path") if isinstance(settings, dict) else None
        selected = db_path or (
            Path(configured).expanduser() if configured else data_dir() / "ojaudit.sqlite"
        )
        self.contests = contests if contests is not None else LocalContests(selected)
        self.job_status = "空闲"
        self._job_task: asyncio.Task[None] | None = None
        self._cancel_job = Event()
        self.source_factory = None
        self.wallpaper_source = ""
        self.wallpaper_signature: tuple[int, int] | None = None
        self.synced_joined = False
        self._config_signature = self._config_mtime()
        self.load_appearance(self._configured_appearance())

    # ── 外观 ────────────────────────────────────────────

    @staticmethod
    def _configured_appearance() -> dict[str, Any]:
        appearance = load_config().get("appearance", {})
        return appearance if isinstance(appearance, dict) else {}

    @staticmethod
    def _config_mtime() -> tuple[int, int] | None:
        path = config_dir() / "config.toml"
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def load_appearance(self, values: dict[str, Any]) -> None:
        self.theme_name = str(values.get("theme", "auto"))
        self.nerd_font = bool(values.get("nerd_font", False))
        self.key_hints = bool(values.get("key_hints", True))
        self.transparent = bool(values.get("transparent", False))
        self.border_style = str(values.get("border", "round"))
        if self.border_style not in {"round", "solid", "heavy", "double", "ascii"}:
            self.border_style = "round"
        self.syntax_choice = str(values.get("syntax_theme", "auto"))
        self.line_numbers = bool(values.get("line_numbers", True))

    def apply_appearance(self, values: dict[str, Any]) -> None:
        """设置页修改外观或配置文件变化时立即生效。"""
        self.load_appearance(values)
        self._apply_theme()
        self.refresh_css()
        self._redraw()

    @property
    def ansi_mode(self) -> bool:
        return self.transparent or self.theme.startswith("ansi-")

    @property
    def syntax_theme(self) -> str:
        if self.syntax_choice != "auto":
            return self.syntax_choice
        if self.ansi_mode:
            return "ansi_light" if self.current_theme.dark is False else "ansi_dark"
        return "monokai" if self.current_theme.dark else "default"

    def get_css_variables(self) -> dict[str, str]:
        variables = super().get_css_variables()
        variables["border-style"] = getattr(self, "border_style", "round")
        if getattr(self, "transparent", False):
            variables["background"] = "ansi_default"
        return variables

    def _redraw(self) -> None:
        if not self.screen_stack:
            return
        screen = self.screen

        def redraw() -> None:
            # 排队期间页面可能已关闭（如放弃设置后返回），只重绘仍在栈顶的页面。
            handler = getattr(screen, "on_layout_change", None)
            if screen is self.screen and screen.is_attached and callable(handler):
                handler()

        self.call_after_refresh(redraw)

    def on_mount(self) -> None:
        self._apply_theme()
        self.refresh_css()
        self.push_screen(HomeScreen())
        self.set_interval(2, self.poll_changes)

    @property
    def job_running(self) -> bool:
        return self._job_task is not None and not self._job_task.done()

    def _publish_job(self, message: str, finished: bool = False) -> None:
        self.job_status = message
        if not self.screen_stack:
            return
        screen = self.screen
        if hasattr(screen, "_update_status"):
            screen._update_status()
        if finished and hasattr(screen, "on_workflow_finished"):
            screen.on_workflow_finished()

    def start_workflow(self, contest_id: str, mode: str, platform: str = "nowcoder") -> None:
        if self.job_running:
            self.notify("已有任务执行中；请先完成或取消", severity="warning")
            return
        if mode not in {"collect", "collect_analyze", "analyze"}:
            raise ValueError("未知工作流模式")
        if not contest_id.strip():
            self.notify("比赛 ID 不能为空", severity="warning")
            return
        self._cancel_job.clear()
        self._job_task = asyncio.create_task(
            self._perform_workflow(contest_id.strip(), mode, platform)
        )

    def cancel_workflow(self) -> None:
        if not self.job_running:
            self.notify("没有正在运行的任务")
            return
        self._cancel_job.set()
        self._publish_job("已请求取消，等待当前步骤安全结束")

    async def _perform_workflow(self, contest_id: str, mode: str, platform: str) -> None:
        from ojaudit.cli_operations import nowcoder_source
        from ojaudit.core.schema import Contest

        try:
            contest = Contest(platform, contest_id, contest_id)
            if mode != "analyze":
                self._publish_job(f"{contest_id} · 正在采集")
                source = (
                    self.source_factory() if self.source_factory is not None else nowcoder_source()
                )
                bundle = await asyncio.to_thread(source.fetch_contest, None, contest_id)
                if self._cancel_job.is_set():
                    self._publish_job("采集后已取消", finished=True)
                    return
                self._publish_job(f"{contest_id} · 正在保存提交")
                contest = await asyncio.to_thread(persist_bundle, self.contests.db_path, bundle)
            if self._cancel_job.is_set():
                self._publish_job("任务已取消", finished=True)
                return
            if mode != "collect":
                self._publish_job(f"{contest.contest_id} · 正在分析")
                await asyncio.to_thread(analyze_local, self.contests.db_path, contest)
            self._publish_job(f"{contest.contest_id} · 任务完成", finished=True)
            self.notify(f"比赛 {contest.contest_id} 已更新")
        except (RuntimeError, ValueError) as exc:
            # 数据源与核心层的这两类异常文字是给用户看的，不含 Cookie 或请求参数。
            self._publish_job("任务失败", finished=True)
            self.notify(str(exc) or "采集或分析失败", severity="error")
        except (OSError, TypeError, sqlite3.Error) as exc:
            self._publish_job(f"任务失败（{type(exc).__name__}）", finished=True)
            self.notify("采集或分析失败，请检查网络、登录状态和数据库", severity="error")
        finally:
            self._job_task = None

    # ── 已参加比赛同步 ──────────────────────────────────

    def sync_joined(self, force: bool = False) -> None:
        """后台拉取账号参加过的比赛，登记为「未采集」；每次启动自动一次，S 键可手动刷新。"""
        from ojaudit.tui.account_service import logged_in_locally

        if (self.synced_joined and not force) or not (self.auto_sync or force):
            return
        if self.source_factory is None and not logged_in_locally():
            if force:
                self.notify("未登录：先在「账户与登录」中扫码", severity="warning")
            return
        self.synced_joined = True
        self.run_worker(self._sync_joined, thread=True, exclusive=True, group="sync")

    def _sync_joined(self) -> None:
        from ojaudit.cli_operations import nowcoder_source
        from ojaudit.core.store import Store
        from ojaudit.tui.account_service import current_uid, detect_and_save_uid

        self.call_from_thread(self._publish_sync, "正在同步已参加的比赛")
        try:
            source = self.source_factory() if self.source_factory is not None else nowcoder_source()
            uid = current_uid() or detect_and_save_uid()
            rows = source.list_joined(uid)
            with Store(self.contests.db_path) as store:
                added = sum(
                    store.put_contest_listing(
                        "nowcoder",
                        row["contest_id"],
                        row["name"],
                        row["start_time"],
                        row["end_time"],
                    )
                    for row in rows
                )
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
            self.call_from_thread(self._publish_sync, "同步失败：检查网络或重新登录", True)
            return
        message = f"已同步 {len(rows)} 场比赛" + (f"，新增 {added}" if added else "")
        self.call_from_thread(self._publish_sync, message, True)

    def _publish_sync(self, message: str, finished: bool = False) -> None:
        if not self.job_running:
            self._publish_job(message, finished)
        elif finished:
            self.notify(message)

    def _fallback_theme(self) -> str:
        return "catppuccin-mocha" if "catppuccin-mocha" in self.available_themes else "textual-dark"

    def _apply_theme(self) -> None:
        choice = self.theme_name
        if choice in ("auto", "wallpaper"):
            wallpaper, path = load_wallpaper_theme()
            if wallpaper is not None:
                self.register_theme(wallpaper)
                self.wallpaper_source = path
                self.wallpaper_signature = wallpaper_signature(path)
                choice = "wallpaper"
            else:
                self.wallpaper_source = ""
                self.wallpaper_signature = None
                choice = self._fallback_theme()
        elif choice not in self.available_themes:
            choice = self._fallback_theme()
        self.ansi_color = choice.startswith("ansi-") or self.transparent
        self.theme = choice
        # 终端调色板无法半透明叠色，ANSI 模式下改用实色高亮（见样式表 App.-ansi）。
        self.set_class(self.ansi_mode, "-ansi")

    def poll_changes(self) -> None:
        """热加载：配置文件被外部修改时重新应用外观；壁纸配色变化时刷新主题。"""
        signature = self._config_mtime()
        if signature != self._config_signature:
            self._config_signature = signature
            self.apply_appearance(self._configured_appearance())
            return
        self.poll_wallpaper()

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

    def watch_theme(self, _theme: str) -> None:
        # 文本颜色在渲染时取自主题，主题变化后需要重绘当前页。
        self._redraw()

    def action_cycle_theme(self) -> None:
        choices = ["auto", *sorted(name for name in self.available_themes if name != "wallpaper")]
        index = choices.index(self.theme_name) if self.theme_name in choices else 0
        self.theme_name = choices[(index + 1) % len(choices)]
        self._apply_theme()
        self.notify(
            label("theme", f"主题：{self.theme_name}（设置 › 外观 可保存）", self.nerd_font)
        )

    def action_context_quit(self) -> None:
        from ojaudit.tui.screens import HomeScreen

        if isinstance(self.screen, HomeScreen):
            self.exit()
        else:
            cancel = getattr(self.screen, "action_cancel", None)
            back = getattr(self.screen, "action_back", None)
            if callable(cancel):
                cancel()
            elif callable(back):
                back()
            else:
                self.pop_screen()

    def action_help(self) -> None:
        from ojaudit.tui.style_help import StyleHelpScreen

        self.push_screen(StyleHelpScreen())


def main(db_path: str | Path | None = None) -> None:
    AuditApp(db_path=db_path, auto_sync=True).run()


if __name__ == "__main__":
    main()
