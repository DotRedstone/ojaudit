"""
Module: Core / schema
Description: 定义平台无关的审查数据对象与字段约束。
Scope: Core
Notes: 标准对象只描述数据，不包含平台会话或 I/O 行为。
"""

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = 1
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
