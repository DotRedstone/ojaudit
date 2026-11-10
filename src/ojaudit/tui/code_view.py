"""
Module: TUI / code view
Description: 证据页的代码对照：规范化格式、忽略头文件与样板、变量名对齐、按行对齐（缺行补空）
    与行内差异着色。
Scope: TUI
Notes:
- 只改变显示，不修改数据库中的代码，也不影响检测结果。
- 规范化基于词法而非语法分析：统一空格与缩进、去注释与空行，目标是「便于人眼比对」，
  不保证输出可编译。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from rich.syntax import Syntax
from rich.text import Text

from ojaudit.plugins.detectors.tokens import _KEYWORDS

LEXERS = {"cpp": "cpp", "python": "python", "java": "java"}

_TOKEN = re.compile(
    r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|'
    r"0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?[uUlLfF]*|"
    r"[^\W\d]\w*|"
    r"<<=|>>=|\*\*=|//=|->|::|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||\*\*|//|"
    r"[+\-*/%&|^]=|[+\-*/%<>=!&|^~?:.,;()\[\]{}@#]|\S"
)
_C_COMMENT = re.compile(r'("(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')|//[^\n]*|/\*[\s\S]*?\*/')
_PY_COMMENT = re.compile(r'("(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')|#[^\n]*')

# 规范化视图中忽略的头文件与常见样板（整行匹配）。
_BOILERPLATE = {
    "cpp": re.compile(
        r"^\s*(#\s*(include|pragma)\b.*|using\s+namespace\s+\w+\s*;|"
        r"(std\s*::\s*)?ios(_base)?\s*::\s*sync_with_stdio\s*\(.*\)\s*;.*|"
        r"(std\s*::\s*)?(cin|cout)\s*\.\s*tie\s*\(.*\)\s*;.*)\s*$"
    ),
    "java": re.compile(r"^\s*(import|package)\s+[\w.*]+\s*;\s*$"),
    "python": re.compile(
        r"^\s*(import\s+[\w., ]+|from\s+[\w.]+\s+import\s+.+|"
        r"input\s*=\s*sys\.stdin\.readline.*|sys\.setrecursionlimit\(.*\))\s*$"
    ),
}
_BINARY = {
    "=", "==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "&&", "||", "+=", "-=", "*=", "/=",
    "%=", "&=", "|=", "^=", "<<", ">>", "<<=", ">>=", "**", "//", "**=", "//=", "&", "|", "^",
    "<", ">", "?", ":",
}  # fmt: skip
_TEMPLATES = {
    "vector", "map", "set", "pair", "array", "queue", "stack", "deque", "priority_queue",
    "unordered_map", "unordered_set", "multiset", "multimap", "tuple", "bitset", "greater",
    "less", "function", "list", "basic_string", "List", "Map", "Set", "ArrayList", "HashMap",
    "HashSet", "TreeMap", "TreeSet", "Deque", "ArrayDeque", "PriorityQueue", "Queue",
}  # fmt: skip
_CALLERS = {"if", "for", "while", "switch", "return", "catch", "elif", "and", "or", "not", "in"}


def strip_comments(code: str, language: str) -> str:
    pattern = _PY_COMMENT if language == "python" else _C_COMMENT
    return pattern.sub(lambda m: m.group(1) or "", code or "")


_PREFIX_CONTEXT = {"return", "case", "in", "and", "or", "not", "if", "elif", "while", "yield"}


def _is_operand(token: str) -> bool:
    """token 结束后是否是一个完整的操作数（决定后面的 - * & 是二元还是一元）。"""
    if not token or token in _PREFIX_CONTEXT:
        return False
    return token[0].isalnum() or token[0] in "_\"'" or token in {")", "]"}


def _join(tokens: list[str], language: str) -> str:
    """按常见代码风格重新拼接一行的记号：二元运算符两侧空格，逗号后空格，调用与下标紧贴。"""
    parts: list[str] = []
    prev = ""
    glue_next = False  # 上一个记号是一元运算符或左括号等，后面紧贴
    template = 0
    for token in tokens:
        space = bool(parts) and not glue_next
        if token in {",", ";", ")", "]", ".", "->", "::"}:
            space = False
        elif token in {"++", "--"} and _is_operand(prev):
            space = False  # 后缀自增
        elif token in {"(", "["} and _is_operand(prev) and prev not in _CALLERS:
            space = False  # 函数调用、下标
        elif token == "<" and prev in _TEMPLATES:
            template += 1
            space = False
        elif token == ">" and template:
            template -= 1
            space = False
        elif token == ":" and language == "python":
            space = False
        parts.append((" " if space else "") + token)
        unary = token in {"-", "+", "*", "&", "!", "~", "++", "--"} and not _is_operand(prev)
        glue_next = unary or token in {"(", "[", ".", "->", "::"} or (template > 0 and token == "<")
        prev = token
    return "".join(parts)


def format_lines(code: str, language: str, hide_boilerplate: bool = True) -> list[str]:
    """规范化：去注释与空行，忽略头文件与 IO 样板，统一空格与 4 空格缩进。"""
    text = strip_comments(code, language).expandtabs(4)
    boilerplate = _BOILERPLATE.get(language)
    result: list[str] = []
    depth = 0
    indents: list[int] = [0]
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if hide_boilerplate and boilerplate is not None and boilerplate.match(raw):
            continue
        tokens = _TOKEN.findall(raw.strip())
        body = _join(tokens, language)
        if language == "python":
            width = len(raw) - len(raw.lstrip())
            while indents and width < indents[-1]:
                indents.pop()
            if width > indents[-1]:
                indents.append(width)
            level = len(indents) - 1
        else:
            leading = len(body) - len(body.lstrip("}"))
            level = max(depth - leading, 0)
            depth = max(depth + body.count("{") - body.count("}"), 0)
        if body == "{" and result and language != "python":
            result[-1] += " {"  # 统一大括号风格：单独一行的 { 并入上一行
            continue
        result.append("    " * level + body)
    return result


def _identifier_spans(line: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"[^\W\d]\w*", line)]


def variable_mapping(lines_a: list[str], lines_b: list[str], language: str) -> dict[str, str]:
    """按结构对齐两份代码，把 B 中的标识符映射为 A 中相同位置的名字（多数票）。"""
    keywords = _KEYWORDS.get(language, set())

    def stream(lines: list[str]) -> list[str]:
        return [token for line in lines for token in _TOKEN.findall(line)]

    a, b = stream(lines_a), stream(lines_b)

    def shape(token: str) -> str:
        return "ID" if re.fullmatch(r"[^\W\d]\w*", token) and token not in keywords else token

    votes: dict[str, Counter[str]] = defaultdict(Counter)
    matcher = SequenceMatcher(None, [shape(t) for t in a], [shape(t) for t in b], autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            left, right = a[block.a + offset], b[block.b + offset]
            if shape(left) == "ID":
                votes[right][left] += 1
    mapping = {}
    taken: set[str] = set()
    for name, counter in sorted(votes.items(), key=lambda kv: -sum(kv[1].values())):
        target, _ = counter.most_common(1)[0]
        if target != name and target not in taken:
            mapping[name] = target
            taken.add(target)
    return mapping


def rename(
    lines: list[str], mapping: dict[str, str]
) -> tuple[list[str], list[list[tuple[int, int]]]]:
    """应用变量映射，并返回每行被改名的字符区间（用于下划线标记）。"""
    renamed, marks = [], []
    for line in lines:
        out, spans, last = "", [], 0
        for start, end, name in _identifier_spans(line):
            out += line[last:start]
            if name in mapping:
                spans.append((len(out), len(out) + len(mapping[name])))
                out += mapping[name]
            else:
                out += name
            last = end
        out += line[last:]
        renamed.append(out)
        marks.append(spans)
    return renamed, marks


@dataclass(frozen=True, slots=True)
class Row:
    """对齐后的一行：kind 为 equal / change / delete（仅 A） / insert（仅 B）。"""

    a: int | None
    b: int | None
    kind: str


def align(lines_a: list[str], lines_b: list[str]) -> list[Row]:
    key = lambda line: re.sub(r"\s+", "", line)
    matcher = SequenceMatcher(None, [key(x) for x in lines_a], [key(x) for x in lines_b], False)
    rows: list[Row] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rows += [Row(i1 + k, j1 + k, "equal") for k in range(i2 - i1)]
            continue
        left, right = list(range(i1, i2)), list(range(j1, j2))
        for k in range(max(len(left), len(right))):
            a = left[k] if k < len(left) else None
            b = right[k] if k < len(right) else None
            kind = (
                "change"
                if a is not None and b is not None
                else ("delete" if b is None else "insert")
            )
            rows.append(Row(a, b, kind))
    return rows


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
    parts = text.split("\n", allow_blank=True)
    parts += [Text("")] * (len(lines) - len(parts))
    for part in parts:
        part.style = ""
    return parts[: len(lines)]


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


def diff_stats(rows: list[Row]) -> Counter[str]:
    return Counter(row.kind for row in rows)
