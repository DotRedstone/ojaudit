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
from typing import ClassVar

from textual.app import App

from ojaudit.core.config import data_dir, load_config
from ojaudit.tui.data import LocalContests
from ojaudit.tui.screens import HomeScreen
from ojaudit.tui.workflow import analyze_local, persist_bundle


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
        self.job_status = "空闲"
        self._job_task: asyncio.Task[None] | None = None
        self._cancel_job = Event()
        self.source_factory = None

    def on_mount(self) -> None:
        self._apply_theme()
        self.push_screen(HomeScreen())

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
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error) as exc:
            # 异常文本可能带请求参数，因此界面不回显异常内容或 Cookie。
            self._publish_job(f"任务失败（{type(exc).__name__}）", finished=True)
            self.notify("采集或分析失败，请检查比赛 ID、登录状态和检测配置", severity="error")
        finally:
            self._job_task = None

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
        self.notify(f"主题：{self.theme_name}（设置页可保存）")

    def action_help(self) -> None:
        self.notify("j/k 移动 · g/G 首尾 · Enter/l 进入 · Esc/h 返回 · a 全部 · t 主题 · q 退出")


def main(db_path: str | Path | None = None) -> None:
    AuditApp(db_path=db_path).run()


if __name__ == "__main__":
    main()
