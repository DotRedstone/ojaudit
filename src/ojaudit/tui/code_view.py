"""
Module: TUI / code view
Description: 证据页的代码对照渲染：语法高亮、缺行补位、改动底色与行内差异加重。
Scope: TUI
Notes:
- 规范化、对齐与变量重命名算法在 core.code_diff；本模块只负责把它排成终端文本。
- 只改变显示，不修改数据库中的代码，也不影响检测结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from rich.style import Style
from rich.syntax import Syntax
from rich.text import Span, Text

from ojaudit.core.code_diff import (
    LEXERS,
    Row,
    ViewOptions,
    align,
    diff_stats,
    format_lines,
    prepare_lines,
    rename,
    strip_comments,
    variable_mapping,
)

__all__ = [
    "DiffColors",
    "Row",
    "ViewOptions",
    "align",
    "diff_stats",
    "format_lines",
    "prepare_lines",
    "rename",
    "render_side",
    "strip_comments",
    "variable_mapping",
]


@dataclass(frozen=True, slots=True)
class DiffColors:
    change: str
    change_strong: str
    delete: str
    insert: str
    filler: str
    muted: str
    renamed: str


def _highlighted(lines: list[str], language: str, theme: str) -> list[Text]:
    if not lines:
        return []
    syntax = Syntax("\n".join(lines), LEXERS.get(language, "text"), theme=theme)
    text = syntax.highlight("\n".join(lines))
    text.rstrip()
    parts = list(text.split("\n", allow_blank=True))
    parts += [Text("")] * (len(lines) - len(parts))
    for part in parts:
        part.style = ""
        # 只保留语法颜色与字形，去掉主题自带的背景，差异底色才能显示出来。
        part.spans = [Span(span.start, span.end, _foreground(span.style)) for span in part.spans]
    return parts[: len(lines)]


def _foreground(style: str | Style) -> Style:
    parsed = Style.parse(style) if isinstance(style, str) else style
    return Style(color=parsed.color, bold=parsed.bold, italic=parsed.italic)


def render_side(
    rows: list[Row],
    side: str,
    lines: list[str],
    other: list[str],
    language: str,
    theme: str,
    colors: DiffColors,
    width: int,
    line_numbers: bool = True,
    renamed: list[list[tuple[int, int]]] | None = None,
) -> Text:
    """渲染对照的一侧：缺行补斜线、改动行黄底、单侧独有行红/绿底、行内差异加深并加粗。"""
    highlighted = _highlighted(lines, language, theme)
    gutter = len(str(len(lines))) + 1 if line_numbers else 0
    out = Text(no_wrap=True)
    for number, row in enumerate(rows):
        if number:
            out.append("\n")
        index = row.a if side == "a" else row.b
        partner = row.b if side == "a" else row.a
        if index is None:
            out.append(" " * gutter, style=colors.muted)
            out.append("╱" * max(width - gutter, 1), style=f"{colors.muted} on {colors.filler}")
            continue
        line = highlighted[index].copy()
        if renamed is not None:
            for start, end in renamed[index]:
                line.stylize(f"underline {colors.renamed}", start, end)
        background = {
            "change": colors.change,
            "delete": colors.delete if side == "a" else colors.insert,
            "insert": colors.insert if side == "b" else colors.delete,
        }.get(row.kind)
        if row.kind == "change" and partner is not None:
            this, that = lines[index], other[partner]
            matcher = SequenceMatcher(None, this, that, autojunk=False)
            for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
                if tag != "equal" and i2 > i1:
                    line.stylize(f"bold on {colors.change_strong}", i1, i2)
        if line_numbers:
            out.append(f"{index + 1:>{gutter - 1}} ", style=colors.muted)
        if background:
            pad = max(width - gutter - line.cell_len, 0)
            line.append(" " * pad)
            line.stylize(f"on {background}", 0, len(line))
        out.append_text(line)
    return out
