"""
Module: TUI / account screen
Description: 牛客账户的一层一屏入口，提供扫码登录、UID、粘贴 Cookie 和退出。
Scope: TUI
Notes: 二维码仅打印到暂停的本地终端，不显示在 Textual 屏幕或日志中。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Label, Static

from ojaudit.cli_operations import save_cookie
from ojaudit.tui import ui
from ojaudit.tui.account_service import (
    current_uid,
    detect_and_save_uid,
    logged_in_locally,
    login_with_qr,
    logout,
    qr_half_blocks,
    qr_matrix,
    set_uid,
)
from ojaudit.tui.icons import label
from ojaudit.tui.interaction import NavigateListItem as ListItem
from ojaudit.tui.interaction import NavigateListView
from ojaudit.tui.popup import ConfirmPopup, InputPopup, Popup
from ojaudit.tui.screens import ShellScreen


class UidDialog(InputPopup):
    def __init__(self) -> None:
        super().__init__(
            "牛客 UID",
            current_uid(),
            placeholder="留空则登录后自动识别",
            note="用于列出你参加过的比赛",
            validate=lambda value: (
                None if not value.strip() or value.strip().isdigit() else "UID 只能是数字"
            ),
            input_id="uid-value",
        )


class QrLoginScreen(Popup):
    """在程序内显示扫码二维码并等待手机确认；成功后自动识别 UID。返回是否登录成功。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,q", "cancel", "取消", priority=True),
        Binding("r", "retry", "刷新二维码"),
    ]
    WIDTH = 50
    ICON = "login"
    ACTIONS = (("刷新二维码", "retry"), ("取消", "cancel"))

    def __init__(self, login: Callable[..., None] | None = None) -> None:
        super().__init__("微信扫码登录牛客", "esc 取消")
        self.login = login or login_with_qr
        self.stop = threading.Event()
        self.done = False

    def compose(self) -> ComposeResult:
        yield self.frame(
            Horizontal(Static("正在获取二维码…", id="qr-code"), id="qr-wrap"),
            Static("", id="qr-status"),
        )

    def on_mount(self) -> None:
        super().on_mount()
        self._start()

    def _start(self) -> None:
        self.stop.clear()
        self.done = False
        self.query_one(".popup").border_subtitle = " esc 取消 "
        self.run_worker(self._run, thread=True, exclusive=True)

    def _run(self) -> None:
        def status(message: str) -> None:
            self.app.call_from_thread(self._status, message)

        def show(url: str) -> None:
            self.app.call_from_thread(self._show_qr, url)

        try:
            self.login(status, on_qr=show, cancelled=self.stop.is_set)
        except InterruptedError:
            return
        except (OSError, RuntimeError, TimeoutError, ValueError, TypeError) as exc:
            message = str(exc) if isinstance(exc, (TimeoutError, ValueError)) else "网络请求失败"
            self.app.call_from_thread(self._failed, message)
            return
        uid = ""
        try:
            uid = detect_and_save_uid()
        except (OSError, RuntimeError, ValueError, TypeError):
            pass
        self.app.call_from_thread(self._success, uid)

    def _show_qr(self, url: str) -> None:
        # 二维码固定黑码白底，任何主题与透明背景下手机都能识别。
        lines = qr_half_blocks(qr_matrix(url))
        text = Text("\n".join(lines), style="#000000 on #ffffff", no_wrap=True)
        code = self.query_one("#qr-code", Static)
        code.update(text)
        code.styles.width = len(lines[0])
        self.query_one(".popup").styles.width = max(len(lines[0]) + 4, 40)

    def _status(self, message: str) -> None:
        colors = ui.palette(self.app)
        self.query_one("#qr-status", Static).update(Text(message, style=colors.muted))

    def _failed(self, message: str) -> None:
        colors = ui.palette(self.app)
        self.query_one("#qr-status", Static).update(Text(message, style=colors.danger))
        self.query_one(".popup").border_subtitle = " r 重试  esc 关闭 "

    def _success(self, uid: str) -> None:
        self.done = True
        self.app.notify("登录成功" + (f"，UID {uid}" if uid else "；UID 识别失败，可在设置中填写"))
        self.dismiss(True)

    def action_retry(self) -> None:
        self.stop.set()
        self.query_one("#qr-code", Static).update("正在获取二维码…")
        self._status("")
        self._start()

    def action_cancel(self) -> None:
        self.stop.set()
        self.dismiss(False)


class AccountScreen(ShellScreen):
    TITLE = "账户与登录"
    PATH = "首页 › 账户"
    HINTS = (("↵", "执行"), ("esc", "返回"))
    OPTIONS = ("扫码登录", "设置牛客 UID", "粘贴 Cookie", "退出登录")
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
            ui.dot("已登录（本机 Cookie）", colors.ok)
            if logged_in
            else ui.dot("未登录", colors.muted)
        )
        text.append("\n")
        text.append_text(ui.fit(Text("牛客 UID", style=colors.muted), 10))
        text.append(uid or "未设置（登录后自动识别）", style=colors.fg if uid else colors.muted)
        text.append(
            "\n\n凭据只保存在本机（0600），不会出现在界面、截图或日志中。", style=colors.muted
        )
        self.query_one("#account-state", Static).update(text)

    def open_index(self, index: int) -> None:
        if index == 0:
            self.app.push_screen(QrLoginScreen(), self._after_login)
        elif index == 1:
            self.app.push_screen(UidDialog(), self._save_uid)
        elif index == 2:
            from ojaudit.tui.screens import EntryDialog

            self.app.push_screen(EntryDialog(login=True), self._save_cookie)
        elif index == 3:
            self.app.push_screen(
                ConfirmPopup(
                    "退出登录", "删除本机保存的牛客 Cookie？\n浏览器与环境变量中的登录不受影响。"
                ),
                self._logout,
            )

    def _after_login(self, ok: bool | None) -> None:
        self.refresh_account()
        if ok:
            self.app.synced_joined = False

    def _logout(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        try:
            logout()
        except OSError:
            self.notify("本机 Cookie 删除失败，请检查文件权限", severity="error")
            return
        self.refresh_account()
        self.notify("已退出登录")

    def _save_uid(self, value: str | None) -> None:
        if value is None:
            return
        try:
            if value.strip():
                set_uid(value)
            else:
                detect_and_save_uid()
        except (OSError, RuntimeError, ValueError, TypeError):
            self.notify("UID 无效，或无法从登录态自动识别", severity="warning")
            return
        self.refresh_account()
        self.app.synced_joined = False
        self.notify("牛客 UID 已保存")

    def _save_cookie(self, value: str | None) -> None:
        if value is None:
            return
        try:
            save_cookie(value)
        except (OSError, ValueError):
            self.notify("Cookie 保存失败", severity="error")
            return
        try:
            detect_and_save_uid()
        except (OSError, RuntimeError, ValueError, TypeError):
            pass
        self.refresh_account()
        self.app.synced_joined = False
        self.notify("Cookie 已保存到本机")
