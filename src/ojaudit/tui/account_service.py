"""
Module: TUI / account service
Description: 在本地终端完成牛客扫码认证并管理 UID 与本机凭据。
Scope: TUI
Notes: 二维码只在终端生成和显示；Cookie 不进入 TUI 控件、日志或截图。
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

import qrcode

from ojaudit.cli_operations import cookie_file, save_cookie
from ojaudit.core.config import load_config, save_config

BASE = "https://www.nowcoder.com"
QR_ENDPOINT = BASE + "/oauth2/login/wechat_qr_code"
STATUS_ENDPOINT = BASE + "/oauth2/login/wechat_mp_status"
HEADERS = {"User-Agent": "ojaudit/0.1", "Referer": BASE + "/login"}


def current_uid() -> str:
    settings = load_config().get("nowcoder", {})
    return str(settings.get("uid", "")) if isinstance(settings, dict) else ""


def set_uid(uid: str) -> None:
    value = uid.strip()
    if not value.isdigit():
        raise ValueError("牛客 UID 必须是数字")
    config = load_config()
    options = config.setdefault("nowcoder", {})
    if not isinstance(options, dict):
        raise TypeError("nowcoder 配置无效")
    options["uid"] = value
    save_config(config)


def logged_in_locally() -> bool:
    return cookie_file().is_file()


def logout() -> None:
    """只删除 ojaudit 自己管理的 Cookie；不会修改浏览器或环境变量。"""
    cookie_file().unlink(missing_ok=True)


def _wechat_url(ticket: str) -> str:
    if not isinstance(ticket, str) or len(ticket) > 4096:
        raise ValueError("扫码票据无效")
    try:
        raw = base64.b64decode(ticket + "=" * (-len(ticket) % 4), altchars=b"-_", validate=True)
        decoded = raw.decode("latin-1")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("扫码票据无效") from exc
    match = re.search(r"https?://weixin\.qq\.com/q/[A-Za-z0-9_./?=&%-]+", decoded)
    if match is None:
        raise ValueError("未发现可验证的微信扫码地址")
    return match.group(0)


def qr_matrix(url: str) -> list[list[bool]]:
    """本地生成二维码矩阵（含 2 格静区），不向外部二维码服务发送票据。"""
    qr = qrcode.QRCode(border=2, box_size=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(url)
    qr.make(fit=True)
    return [[bool(pixel) for pixel in row] for row in qr.get_matrix()]


def qr_half_blocks(matrix: list[list[bool]]) -> list[str]:
    """上下两行像素合成一行字符（▀ ▄ █），终端里接近正方形且只占一半高度。

    返回的字符以「深色模块」为前景，调用方需配合白底显示以便手机识别。
    """
    rows = matrix + ([[False] * len(matrix[0])] if len(matrix) % 2 else [])
    lines = []
    for top, bottom in zip(rows[0::2], rows[1::2]):
        lines.append(
            "".join(
                "█" if a and b else "▀" if a else "▄" if b else " " for a, b in zip(top, bottom)
            )
        )
    return lines


def qr_terminal_text(url: str) -> str:
    return "\n".join(qr_half_blocks(qr_matrix(url)))


def _cookie_value(jar: http.cookiejar.CookieJar) -> str:
    cookies = [
        f"{cookie.name}={cookie.value}"
        for cookie in jar
        if cookie.domain == "nowcoder.com" or cookie.domain.endswith(".nowcoder.com")
    ]
    return "; ".join(cookies)


def _valid_token(jar: http.cookiejar.CookieJar) -> bool:
    return any(
        cookie.name in {"t", "NOWCODERCLOUDTOKEN"}
        and bool(cookie.value)
        and (cookie.domain == "nowcoder.com" or cookie.domain.endswith(".nowcoder.com"))
        for cookie in jar
    )


def login_with_qr(
    output: Callable[[str], None] | None = None,
    *,
    on_qr: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    opener: Any = None,
    cookie_jar: http.cookiejar.CookieJar | None = None,
    pause: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """获取扫码地址、轮询确认并把 Cookie 保存到权限 0600 的本机文件。

    on_qr 收到待编码的微信地址（由调用方在本地渲染）；未提供时在终端打印二维码。
    output 只接收不含票据与 Cookie 的状态文字。opener/cookie_jar/pause/clock 供测试注入。
    """
    show = output or (lambda message: print(message, file=sys.__stdout__, flush=True))
    jar = cookie_jar if cookie_jar is not None else http.cookiejar.CookieJar()
    client = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    response = client.open(urllib.request.Request(QR_ENDPOINT, headers=HEADERS), timeout=20)
    data = json.loads(response.read().decode("utf-8"))
    body = data.get("data") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        raise TypeError("扫码接口返回结构无效")
    ticket = body.get("ticket")
    if not isinstance(ticket, str):
        raise TypeError("扫码接口缺少票据")
    expire = body.get("expireSecond", 120)
    if not isinstance(expire, (float, int)) or not 1 <= expire <= 300:
        raise ValueError("扫码过期时间无效")
    url = _wechat_url(ticket)
    if on_qr is not None:
        on_qr(url)
    else:
        show("请使用微信扫一扫，在手机上确认牛客登录：")
        show(qr_terminal_text(url))
    show("等待手机确认…")
    deadline = clock() + expire
    while clock() < deadline:
        if cancelled():
            raise InterruptedError("已取消扫码登录")
        pause(1.5)
        status_url = STATUS_ENDPOINT + "?" + urllib.parse.urlencode({"ticket": ticket})
        try:
            result = client.open(urllib.request.Request(status_url, headers=HEADERS), timeout=20)
            json.loads(result.read().decode("utf-8"))
        except (OSError, TimeoutError, ValueError):
            continue
        if _valid_token(jar):
            save_cookie(_cookie_value(jar))
            show("登录成功")
            return
    raise TimeoutError("二维码已过期，请重新扫码")


def detect_and_save_uid() -> str:
    """用本机 Cookie 识别自己的牛客 UID 并写入配置；失败时保留原配置。"""
    from ojaudit.plugins.sources.nowcoder import NowcoderSource

    uid = NowcoderSource({"cookie": cookie_file().read_text(encoding="utf-8").strip()}).detect_uid()
    set_uid(uid)
    return uid
