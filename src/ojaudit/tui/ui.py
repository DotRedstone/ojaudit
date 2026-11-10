"""
Module: TUI / ui
Description: 统一的终端排版原语：列对齐、语义徽章、进度条、顶栏与按键提示栏。
Scope: TUI
Notes:
- 所有宽度按终端单元格（中文占两格）计算，避免列错位。
- 颜色取自当前 Textual 主题，跟随壁纸主题变化；本模块不读写任何数据。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.cells import cell_len
from rich.text import Text

# 检测等级：旧检测器输出中文分级，示例数据和外部插件可能输出 high/medium/low。
# rank 越小越需要优先复核；未知等级排在最后。
_LEVELS: dict[str, tuple[str, int]] = {
    "实锤": ("实锤", 0),
    "high": ("高", 0),
    "中偏强": ("中偏强", 1),
    "medium": ("中", 1),
    "存疑": ("存疑", 2),
    "low": ("低", 2),
    "排除": ("排除", 3),
}
MARK_NAMES = {"normal": "正常", "suspect": "存疑", "cheater": "作弊者"}


def level_rank(level: object) -> int:
    return _LEVELS.get(str(level).strip().lower(), _LEVELS.get(str(level), ("", 9)))[1]


def level_name(level: object) -> str:
    raw = str(level).strip()
    return _LEVELS.get(raw.lower(), _LEVELS.get(raw, (raw, 9)))[0]


def is_high_priority(level: object) -> bool:
    return level_rank(level) <= 1


@dataclass(frozen=True, slots=True)
class Palette:
    """当前主题的语义色；所有徽章、等级和状态共用。"""

    accent: str
    muted: str
    fg: str
    bg: str
    surface: str
    danger: str
    warn: str
    caution: str
    ok: str

    def level(self, level: object) -> str:
        return (self.danger, self.warn, self.caution, self.muted)[min(level_rank(level), 3)]

    def mark(self, mark: str, hidden: bool = False) -> str:
        if hidden:
            return self.muted
        return {"cheater": self.danger, "suspect": self.caution, "normal": self.ok}.get(
            mark, self.muted
        )


def palette(app: Any) -> Palette:
    theme = getattr(app, "current_theme", None)

    def pick(name: str, fallback: str) -> str:
        value = getattr(theme, name, None) if theme is not None else None
        return str(value) if value else fallback

    fg = pick("foreground", "#cdd6f4")
    return Palette(
        accent=pick("primary", "#89b4fa"),
        muted=_mix(fg, pick("background", "#1e1e2e"), 0.5),
        fg=fg,
        bg=pick("background", "#1e1e2e"),
        surface=pick("surface", "#313244"),
        danger=pick("error", "#f38ba8"),
        warn=pick("warning", "#fab387"),
        caution=pick("accent", "#f9e2af"),
        ok=pick("success", "#a6e3a1"),
    )


def _mix(left: str, right: str, ratio: float) -> str:
    try:
        a = [int(left.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
        b = [int(right.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return left
    return "#" + "".join(f"{round(x * ratio + y * (1 - ratio)):02x}" for x, y in zip(a, b))


def fit(value: str | Text, width: int, align: str = "left") -> Text:
    """按单元格宽度截断或补齐；超长时以省略号结尾。"""
    text = value.copy() if isinstance(value, Text) else Text(str(value))
    text.no_wrap = True
    if text.cell_len > width:
        text.truncate(max(width - 1, 0))
        while text.cell_len > max(width - 1, 0):
            text.right_crop(1)
        text.append("…")
    gap = width - text.cell_len
    if gap > 0:
        if align == "right":
            text = Text(" " * gap) + text
        else:
            text.append(" " * gap)
    return text


@dataclass(frozen=True, slots=True)
class Column:
    title: str
    width: int = 0  # 0 表示弹性列，占用剩余宽度
    align: str = "left"


def layout(columns: Sequence[Column], total: int) -> list[int]:
    fixed = sum(c.width for c in columns) + 2 * (len(columns) - 1)
    flex = [c for c in columns if not c.width]
    spare = max(total - fixed, 8 * len(flex))
    share = spare // len(flex) if flex else 0
    return [c.width or share for c in columns]


def table_row(cells: Iterable[str | Text], columns: Sequence[Column], total: int) -> Text:
    widths = layout(columns, total)
    row = Text(no_wrap=True)
    for index, (cell, column, width) in enumerate(zip(cells, columns, widths)):
        if index:
            row.append("  ")
        row.append_text(fit(cell, width, column.align))
    return row


def table_header(columns: Sequence[Column], total: int, color: str) -> Text:
    header = table_row([c.title for c in columns], columns, total)
    header.stylize(f"bold {color}")
    return header


def chip(label: str, color: str) -> Text:
    """实心色块标签，用于等级等需要一眼识别的状态。"""
    return Text(f" {label} ", style=f"bold #11111b on {color}")


def dot(label: str, color: str) -> Text:
    """圆点 + 文字，比实心色块更安静，用于列表中的状态。"""
    text = Text("● ", style=color)
    text.append(label, style=color)
    return text


def bar(value: float, width: int, color: str, track: str) -> Text:
    value = min(max(value, 0.0), 1.0)
    filled = round(value * width)
    text = Text("━" * filled, style=color)
    text.append("━" * (width - filled), style=track)
    return text


def progress(done: int, total: int, colors: Palette, width: int = 8) -> Text:
    if total <= 0:
        return Text("—", style=colors.muted)
    text = bar(done / total, width, colors.ok if done == total else colors.accent, colors.surface)
    text.append(f" {done}/{total}", style=colors.fg if done < total else colors.ok)
    return text


def percent(value: object) -> str:
    try:
        return f"{float(value):.0%}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)


def clock(timestamp: object) -> str:
    """提交时间统一为毫秒；过小的值视为合成或相对时间，原样显示。"""
    try:
        value = int(timestamp)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return str(timestamp)
    if value < 10**11:
        return str(value)
    return datetime.fromtimestamp(value / 1000).astimezone().strftime("%m-%d %H:%M:%S")


def duration(seconds: object) -> str:
    try:
        total = round(float(seconds))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} 时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"


def verdict_color(verdict: str, colors: Palette) -> str:
    raw = str(verdict)
    if any(mark in raw for mark in ("答案正确", "Accepted", "通过")) or raw.upper() == "AC":
        return colors.ok
    if any(mark in raw for mark in ("编译", "Compile")) or raw.upper() == "CE":
        return colors.muted
    return colors.danger


def keybar(hints: Sequence[tuple[str, str]], colors: Palette, right: str, width: int) -> Text:
    bar_text = Text(no_wrap=True)
    for index, (key, action) in enumerate(hints):
        if index:
            bar_text.append("   ")
        bar_text.append(key, style=f"bold {colors.accent}")
        bar_text.append(f" {action}", style=colors.muted)
    gap = width - bar_text.cell_len - cell_len(right) - 2
    if gap > 0:
        bar_text.append(" " * gap)
        bar_text.append(right, style=colors.muted)
    return bar_text
