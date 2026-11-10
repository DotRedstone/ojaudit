"""
Module: TUI / icons
Description: Nerd Font 图标的唯一映射；关闭时退回纯文字。
Scope: TUI
Notes: 关闭图标时绝不输出 U+E000–U+F8FF 私有区字符。
"""

from __future__ import annotations

# 图标均来自 Nerd Fonts 常用私有区码位；无图标字体时使用文字标签。
GLYPHS: dict[str, str] = {
    "home": "\uf015",
    "contest": "\uf11b",
    "list": "\uf03a",
    "open": "\uf07c",
    "login": "\uf2bd",
    "settings": "\uf013",
    "pending": "\uf046",
    "collect": "\uf019",
    "collect_analyze": "\uf085",
    "analyze": "\uf002",
    "findings": "\uf071",
    "people": "\uf0c0",
    "person": "\uf007",
    "problems": "\uf02d",
    "problem": "\uf15c",
    "submissions": "\uf121",
    "code": "\uf121",
    "evidence": "\uf0f6",
    "ranking": "\uf091",
    "review": "\uf046",
    "mark": "\uf02b",
    "export": "\uf019",
    "save": "\uf0c7",
    "cancel": "\uf00d",
    "back": "\uf060",
    "next": "\uf061",
    "status": "\uf111",
    "theme": "\uf53f",
    "idle": "\uf017",
    "warning": "\uf06a",
    "success": "\uf00c",
    "filter": "\uf0b0",
    "all": "\uf06e",
    "hidden": "\uf070",
    "normal": "\uf00c",
    "suspect": "\uf059",
    "cheater": "\uf05e",
    "manager": "\uf023",
    "diff": "\uf074",
    "help": "\uf059",
}


def glyph(key: str, enabled: bool) -> str:
    """返回图标或空字符串；禁用时绝不输出 Nerd Font PUA。"""
    return GLYPHS.get(key, "") if enabled else ""


def label(key: str, text: str, enabled: bool) -> str:
    mark = glyph(key, enabled)
    return f"{mark} {text}" if mark else text


def enabled_for(widget: object) -> bool:
    app = getattr(widget, "app", None)
    return bool(getattr(app, "nerd_font", False))
