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
    match = re.search(r"https?://weixin\\.qq\\.com/q/[A-Za-z0-9_./?=&%\\-]+", decoded)
    if match is None:
        raise ValueError("未发现可验证的微信扫码地址")
    return match.group(0)


def qr_terminal_text(url: str) -> str:
    """使用本地二维码编码器，不向外部二维码生成网站发送票据。"""
    qr = qrcode.QRCode(border=2, box_size=1)
    qr.add_data(url)
    qr.make(fit=True)
    return "\\n".join(
        "".join("██" if pixel else "  " for pixel in row) for row in qr.get_matrix()
    )


def _cookie_value(jar: http.cookiejar.CookieJar) -> str:
    cookies = [
        f"{cookie.name}={cookie.value}"
        for cookie in jar
        if cookie.domain == "nowcoder.com" or cookie.domain.endswith(".nowcoder.com")
    ]
    return "; ".join(cookies)


def _valid_token(jar: http.cookiejar.CookieJar) -> bool:
    return any(
        cookie.name in {"t", "NOWCODERCLOUDTOKEN"} and bool(cookie.value)
        and (cookie.domain == "nowcoder.com" or cookie.domain.endswith(".nowcoder.com"))
        for cookie in jar
    )


def login_with_qr(
    output: Callable[[str], None] | None = None,
    *,
    opener: Any = None,
    pause: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """在终端显示二维码、轮询确认并将 Cookie 保存到权限 0600 的本机文件。

    opener/pause/clock 只供合成测试注入，不允许界面输出票据、Cookie 或接口正文。
    """
    show = output or (lambda message: print(message, file=sys.__stdout__, flush=True))
    jar = http.cookiejar.CookieJar()
    client = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    response = client.open(urllib.request.Request(QR_ENDPOINT, headers=HEADERS), timeout=20)
    data = json.loads(response.read().decode("utf-8"))
    body = data.get("data") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        raise ValueError("扫码接口返回结构无效")
    ticket = body.get("ticket")
    if not isinstance(ticket, str):
        raise ValueError("扫码接口缺少票据")
    expire = body.get("expireSecond", 120)
    if not isinstance(expire, (float, int)) or not 1 <= expire <= 300:
        raise ValueError("扫码过期时间无效")
    show("请使用微信扫一扫，在手机上确认牛客登录：")
    show(qr_terminal_text(_wechat_url(ticket)))
    deadline = clock() + expire
    while clock() < deadline:
        pause(3)
        url = STATUS_ENDPOINT + "?" + urllib.parse.urlencode({"ticket": ticket})
        try:
            result = client.open(urllib.request.Request(url, headers=HEADERS), timeout=20)
            status = json.loads(result.read().decode("utf-8"))
        except (OSError, TimeoutError, ValueError):
            continue
        if isinstance(status, dict) and status.get("code") == 0 and _valid_token(jar):
            save_cookie(_cookie_value(jar))
            show("扫码登录成功，凭据已保存在本机。")
            return
        if _valid_token(jar):
            save_cookie(_cookie_value(jar))
            show("扫码登录成功，凭据已保存在本机。")
            return
    raise TimeoutError("扫码确认超时")
