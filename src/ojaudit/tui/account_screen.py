"""
Module: TUI / account screen
Description: 牛客账户的一层一屏入口，提供扫码登录、UID、粘贴 Cookie 和退出。
Scope: TUI
Notes: 二维码仅打印到暂停的本地终端，不显示在 Textual 屏幕或日志中。
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, Static

from ojaudit.cli_operations import save_cookie
from ojaudit.tui import ui
from ojaudit.tui.account_service import (
    current_uid,
    logged_in_locally,
    login_with_qr,
    logout,
    set_uid,
)
from ojaudit.tui.icons import label
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView
from ojaudit.tui.screens import Dialog, ShellScreen, dialog_buttons


class UidDialog(Dialog):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "取消", priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="uid-dialog", classes="dialog"):
            yield Label(label("person", "设置牛客 UID", self.app.nerd_font), classes="dialog-title")
            yield Label("仅接受数字，用于列出自己可见的比赛", classes="dialog-hint")
            yield Input(value=current_uid(), placeholder="牛客 UID", id="uid-value")
            yield dialog_buttons(("uid-save", "保存"), ("uid-cancel", "取消"), self.app.nerd_font)

    def on_mount(self) -> None:
        self.query_one("#uid-value", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(
            self.query_one("#uid-value", Input).value if event.button.id == "uid-save" else None
        )


class AccountScreen(ShellScreen):
    TITLE = "账户与登录"
    PATH = "首页 › 账户"
    HINTS = (("↵", "执行"), ("esc", "返回"))
    OPTIONS = ("扫码登录（本地终端显示二维码）", "设置牛客 UID", "粘贴 Cookie（备选）", "退出登录")
    ICON_KEYS = ("login", "settings", "save", "cancel")

    def compose(self) -> ComposeResult:
        rows = [
            Static("", id="account-state", classes="panel"),
            NavigateListView(
                *(
                    ListItem(Label(label(key, name, self.app.nerd_font)))
                    for key, name in zip(self.ICON_KEYS, self.OPTIONS)
                ),
                id="account-options",
            ),
        ]
        yield from self.shell(rows)

    def on_mount(self) -> None:
        self.query_one("#account-state").border_title = "当前状态"
        super().on_mount()
        self.refresh_account()

    def refresh_account(self) -> None:
        colors = ui.palette(self.app)
        logged_in = logged_in_locally()
        uid = current_uid()
        text = Text()
        text.append_text(ui.fit(Text("牛客登录", style=colors.muted), 10))
        text.append_text(
            ui.dot("本机已保存 Cookie", colors.ok) if logged_in else ui.dot("未登录", colors.muted)
        )
        text.append("\n")
        text.append_text(ui.fit(Text("牛客 UID", style=colors.muted), 10))
        text.append(uid or "尚未设置", style=colors.fg if uid else colors.muted)
        text.append(
            "\n\n扫码只在本地终端进行；凭据不会出现在界面、截图或日志中。", style=colors.muted
        )
        self.query_one("#account-state", Static).update(text)

    def open_index(self, index: int) -> None:
        if index == 0:
            asyncio.create_task(self._qr_flow())
        elif index == 1:
            self.app.push_screen(UidDialog(), self._save_uid)
        elif index == 2:
            from ojaudit.tui.screens import EntryDialog

            self.app.push_screen(EntryDialog(login=True), self._save_cookie)
        elif index == 3:
            try:
                logout()
            except OSError:
                self.notify("本机 Cookie 删除失败，请检查文件权限", severity="error")
                return
            self.refresh_account()
            self.notify("已退出本机 Cookie 登录；环境变量中的凭据不受影响")

    async def _qr_flow(self) -> None:
        try:
            with self.app.suspend():
                await asyncio.to_thread(login_with_qr)
        except (OSError, RuntimeError, TimeoutError, ValueError):
            self.notify("扫码登录未完成，请检查本地终端和网络", severity="warning")
        else:
            self.refresh_account()
            self.notify("扫码登录成功，Cookie 已安全保存到本机")

    def _save_uid(self, value: str | None) -> None:
        if value is None:
            return
        try:
            set_uid(value)
        except (OSError, ValueError, TypeError):
            self.notify("无效 UID 或配置无法保存", severity="warning")
            return
        self.refresh_account()
        self.notify("牛客 UID 已保存")

    def _save_cookie(self, value: str | None) -> None:
        if value is None:
            return
        try:
            save_cookie(value)
        except (OSError, ValueError):
            self.notify("Cookie 保存失败", severity="error")
            return
        self.refresh_account()
        self.notify("Cookie 已保存到本机")
