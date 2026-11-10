"""
Module: Detector / tokens
Description: 代码词法归一化：去注释，标识符按首次出现重命名，数字与字符串字面量归一。
Scope: Detector
Notes: 规则与旧 nowcoder-collect 检测器保持一致，保证历史结果可复现。
"""

from __future__ import annotations

import difflib
import re
from typing import Any

_KEYWORDS = {
    "cpp": {
        "alignas",
        "alignof",
        "and",
        "asm",
        "auto",
        "bool",
        "break",
        "case",
        "catch",
        "char",
        "class",
        "const",
        "constexpr",
        "continue",
        "default",
        "delete",
        "do",
        "double",
        "else",
        "enum",
        "explicit",
        "extern",
        "false",
        "float",
        "for",
        "friend",
        "if",
        "inline",
        "int",
        "long",
        "namespace",
        "new",
        "nullptr",
        "operator",
        "private",
        "protected",
        "public",
        "return",
        "short",
        "signed",
        "sizeof",
        "static",
        "struct",
        "switch",
        "template",
        "this",
        "throw",
        "true",
        "try",
        "typedef",
        "typename",
        "union",
        "unsigned",
        "using",
        "virtual",
        "void",
        "volatile",
        "while",
    },
    "python": {
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    },
    "java": {
        "abstract",
        "assert",
        "boolean",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "class",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extends",
        "final",
        "finally",
        "float",
        "for",
        "if",
        "implements",
        "import",
        "instanceof",
        "int",
        "interface",
        "long",
        "native",
        "new",
        "package",
        "private",
        "protected",
        "public",
        "return",
        "short",
        "static",
        "super",
        "switch",
        "synchronized",
        "this",
        "throw",
        "throws",
        "try",
        "void",
        "volatile",
        "while",
        "true",
        "false",
        "null",
    },
}
_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
    r"\b0[xX][0-9a-fA-F]+\b|\b\d+(?:\.\d*)?(?:[eE][+-]?\d+)?\b|"
    r"[^\W\d]\w*|<<|>>|<=|>=|==|!=|\+\+|--|&&|\|\||->|::|"
    r"[+\-*/%<>=!&|^~?:.,;()\[\]{}@]|\S",
    re.UNICODE,
)
_COMMENT = re.compile(r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|//[^\n]*|/\*[\s\S]*?\*/|#[^\n]*')


def _strip_comments(code: str) -> str:
    return _COMMENT.sub(lambda match: match.group(1) or " ", code)


def normalize_tokens(code: str, language: str) -> list[str]:
    """将标识符按首次出现重命名，数字/字符串归一化。"""
    lang = language if language in _KEYWORDS else "other"
    keywords = _KEYWORDS.get(lang, set())
    names: dict[str, str] = {}
    result = []
    for token in _TOKEN.findall(_strip_comments(code)):
        if token.startswith(("'", '"')):
            result.append("STR")
        elif token[0].isdigit():
            result.append("NUM")
        elif token.isidentifier() and token not in keywords:
            if token not in names:
                names[token] = f"v{len(names)}"
            result.append(names[token])
        else:
            result.append(token)
    return result


def ratio(left: Any, right: Any) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def ngrams(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    if size < 1:
        raise ValueError("n-gram 窗口必须为正整数")
    return {tuple(tokens[index : index + size]) for index in range(max(0, len(tokens) - size + 1))}
