"""
Module: Core / schema
Description: 定义平台无关的审查数据对象与字段约束。
Scope: Core
Notes: 标准对象只描述数据，不包含平台会话或 I/O 行为。
"""

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = 3
Language = Literal["cpp", "python", "java", "other"]
Phase = Literal["before", "contest", "after"]


@dataclass(frozen=True, slots=True)
class Contest:
    platform: str
    contest_id: str
    name: str
    start_time: int | None = None
    end_time: int | None = None
    raw_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Problem:
    platform: str
    contest_id: str
    index: int
    problem_id: str
    title: str
    full_score: float | None = None


@dataclass(frozen=True, slots=True)
class Participant:
    platform: str
    contest_id: str
    uid: str
    name: str


@dataclass(frozen=True, slots=True)
class Submission:
    platform: str
    contest_id: str
    submission_id: str
    uid: str
    problem_index: int
    language: Language
    verdict: str
    score: float
    submit_time: int
    phase: Phase
    code: str
    raw_meta: dict[str, Any] = field(default_factory=dict)


def validate_submission(item: Submission) -> None:
    if not all((item.platform, item.contest_id, item.submission_id, item.uid)):
        raise ValueError("提交记录的平台、比赛、提交和用户标识不能为空")
    if item.problem_index < 0:
        raise ValueError("题目序号不能为负数")
    if item.language not in {"cpp", "python", "java", "other"}:
        raise ValueError("不支持的语言桶")
    if item.phase not in {"before", "contest", "after"}:
        raise ValueError("不支持的提交阶段")


def language_bucket(value: str) -> Language:
    """把平台语言名归入 cpp / python / java / other。"""
    text = (value or "").lower()
    if any(token in text for token in ("c++", "cpp", "g++", "clang")):
        return "cpp"
    if "python" in text or "pypy" in text:
        return "python"
    if "java" in text and "javascript" not in text:
        return "java"
    return "other"


def parse_problem_index(value: object) -> int:
    """题号统一为从 0 开始的整数：数字原样，字母按 A=0、Z=25、AA=26 计算。"""
    text = str(value).strip().upper()
    if text.isdigit():
        return int(text)
    if text.isascii() and text.isalpha():
        number = 0
        for char in text:
            number = number * 26 + (ord(char) - ord("A") + 1)
        return number - 1
    raise ValueError(f"无法识别的题号：{value!r}")


def is_accepted(verdict: str) -> bool:
    """提交是否通过；兼容 AC / Accepted / 答案正确 / 通过，排除「未通过」「部分通过」。"""
    text = (verdict or "").strip()
    if text.upper() in {"AC", "ACCEPTED", "OK"} or text.lower().startswith("accepted"):
        return True
    return "答案正确" in text or text == "通过"
