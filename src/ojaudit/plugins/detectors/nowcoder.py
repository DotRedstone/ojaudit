"""
Module: Detector / nowcoder
Description: 迁移牛客代码相似度、稀有片段、模板与时间线规则。
Scope: Detector
Notes:
- 仅分析调用方传入的标准化提交，不读取平台数据库或凭据。
- 结果排序稳定且不访问网络；结论只作为人工复核线索。
"""

import difflib
import hashlib
import re
from collections import defaultdict
from typing import Any

from ojaudit.core.schema import Submission

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


def _ratio(left: Any, right: Any) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _ngrams(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[index : index + size]) for index in range(max(0, len(tokens) - size + 1))}


def _error_type(verdict: str) -> str:
    checks = (
        (("编译", "Compile"), "编译错误"),
        (("超时", "Time", "TLE"), "超时"),
        (("内存", "Memory"), "内存超限"),
        (("答案", "Wrong", "WA"), "答案错误"),
        (("段错误", "Seg"), "段错误"),
        (("格式", "Presentation"), "格式错误"),
        (("输出",), "输出超限"),
    )
    for markers, label in checks:
        if any(marker in verdict for marker in markers):
            return label
    return verdict or "未知"


def _is_ac(verdict: str) -> bool:
    return any(marker in (verdict or "") for marker in ("答案正确", "Accepted", "通过"))


def _timeline(left: list[Submission], right: list[Submission]) -> dict[str, Any]:
    a = sorted(left, key=lambda item: (item.submit_time, item.submission_id))
    b = sorted(right, key=lambda item: (item.submit_time, item.submission_id))
    first_delta = round(abs(a[0].submit_time - b[0].submit_time) / 1000, 1)
    ac_a = min((item.submit_time for item in a if _is_ac(item.verdict)), default=None)
    ac_b = min((item.submit_time for item in b if _is_ac(item.verdict)), default=None)
    who = (
        "A"
        if ac_a is not None and (ac_b is None or ac_a <= ac_b)
        else ("B" if ac_b is not None else None)
    )
    delta = round(abs(ac_a - ac_b) / 1000, 1) if ac_a is not None and ac_b is not None else None
    direction = (who == "A" and ac_a is not None and b[0].submit_time >= ac_a) or (
        who == "B" and ac_b is not None and a[0].submit_time >= ac_b
    )
    later = b if who == "A" else a
    later_ac = ac_b if who == "A" else ac_a
    failures = [
        _error_type(item.verdict)
        for item in later
        if not _is_ac(item.verdict) and (later_ac is None or item.submit_time < later_ac)
    ]
    return {
        "who_first": who,
        "delta_seconds": delta,
        "first_submit_delta": first_delta,
        "later_failures_before_ac": len(failures),
        "direction_valid": bool(direction),
        "error_types": failures[:10],
    }


def analyze(
    submissions: list[Submission],
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """运行确定性两两比较；只比较同题、同语言且不同 UID 的代表提交。"""
    submissions = getattr(submissions, "submissions", submissions)
    config = parameters or {}
    ngram_size = int(config.get("ngram_size", 5))
    rare_limit = int(config.get("rare_threshold", 3))
    thresholds = {
        "solid_l2": 0.98,
        "solid_delta_seconds": 1800,
        "mid_strong_rare": 0.5,
        "mid_strong_l3": 0.85,
        "suspicious_l3": 0.8,
        "suspicious_rare": 0.3,
        "crowd_threshold": 3,
        **config.get("thresholds", {}),
    }
    groups: dict[tuple[str, str], dict[str, list[Submission]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in submissions:
        if item.code.strip():
            groups[(item.problem_index, item.language)][item.uid].append(item)

    results = []
    for (problem, language), students in sorted(groups.items()):
        representatives = {
            uid: max(items, key=lambda item: (item.score, len(item.code), -item.submit_time))
            for uid, items in sorted(students.items())
        }
        tokens = {
            uid: normalize_tokens(item.code, language) for uid, item in representatives.items()
        }
        usage: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for uid, token_list in tokens.items():
            for gram in _ngrams(token_list, ngram_size):
                usage[gram].add(uid)
        rare = {
            uid: {
                gram for gram in _ngrams(token_list, ngram_size) if len(usage[gram]) <= rare_limit
            }
            for uid, token_list in tokens.items()
        }
        normalized_hashes = {
            uid: hashlib.md5(re.sub(r"\s+", "", item.code).encode()).hexdigest()
            for uid, item in representatives.items()
        }
        crowd: dict[str, int] = defaultdict(int)
        for digest in normalized_hashes.values():
            crowd[digest] += 1

        uids = sorted(representatives)
        for index, uid_a in enumerate(uids):
            for uid_b in uids[index + 1 :]:
                a, b = representatives[uid_a], representatives[uid_b]
                code_a, code_b = a.code, b.code
                ta, tb = tokens[uid_a], tokens[uid_b]
                equal = normalized_hashes[uid_a] == normalized_hashes[uid_b]
                scores = {
                    "L1": round(_ratio(code_a, code_b), 4),
                    "L2": round(_ratio(re.sub(r"\s+", "", code_a), re.sub(r"\s+", "", code_b)), 4),
                    "L3": round(_ratio(ta, tb), 4),
                    "md5_ws_equal": equal,
                }
                shared = rare[uid_a] & rare[uid_b]
                rare_score = (
                    len(shared) / min(len(rare[uid_a]), len(rare[uid_b]))
                    if (rare[uid_a] and rare[uid_b])
                    else 0.0
                )
                rare_info = {
                    "shared": len(shared),
                    "score": round(rare_score, 4),
                    "samples": [" ".join(gram) for gram in sorted(shared)[:8]],
                }
                timeline = (
                    _timeline(students[uid_a], students[uid_b])
                    if config.get("enable_timeline", True)
                    else {}
                )
                crowd_count = (
                    crowd[normalized_hashes[uid_a]]
                    if equal and config.get("enable_template", True)
                    else 1
                )
                verdict = "排除"
                if not (equal and crowd_count >= thresholds["crowd_threshold"]):
                    if equal or scores["L2"] >= thresholds["solid_l2"]:
                        if (
                            timeline.get("direction_valid", False)
                            and timeline.get("delta_seconds") is not None
                            and timeline["delta_seconds"] < thresholds["solid_delta_seconds"]
                        ):
                            verdict = "实锤"
                        elif equal:
                            verdict = "中偏强"
                    if (
                        verdict == "排除"
                        and rare_score >= thresholds["mid_strong_rare"]
                        and scores["L3"] >= thresholds["mid_strong_l3"]
                    ):
                        verdict = "中偏强"
                    elif (
                        verdict == "排除"
                        and scores["L3"] >= thresholds["suspicious_l3"]
                        and rare_score >= thresholds["suspicious_rare"]
                    ):
                        verdict = "存疑"
                results.append(
                    {
                        "pair": [uid_a, uid_b],
                        "problem": problem,
                        "language": language,
                        "verdict": verdict,
                        "scores": scores,
                        "rare": rare_info,
                        "timeline": timeline,
                        "crowd_count": crowd_count,
                    }
                )
    return sorted(
        results,
        key=lambda row: (row["problem"], row["language"], row["pair"], row["verdict"]),
    )
