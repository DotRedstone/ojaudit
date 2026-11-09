"""
Module: Core / people
Description: 全局隐藏人员名单与检测输入过滤。
Scope: Core
Notes: 以 platform + uid 标识；必须在 pair 分组/比较前过滤。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ojaudit.core.schema import Participant, Submission


@dataclass(frozen=True, slots=True)
class HiddenPerson:
    platform: str
    uid: str
    nickname: str = ""

    def __post_init__(self) -> None:
        if not self.platform or not self.uid:
            raise ValueError("隐藏人员必须提供 platform 和 uid")


def hidden_person_keys(people: Iterable[HiddenPerson]) -> frozenset[tuple[str, str]]:
    return frozenset((person.platform, person.uid) for person in people)


def exclude_hidden_participants(
    participants: Iterable[Participant], people: Iterable[HiddenPerson]
) -> tuple[Participant, ...]:
    hidden = hidden_person_keys(people)
    return tuple(person for person in participants if (person.platform, person.uid) not in hidden)


def exclude_hidden_submissions(
    submissions: Iterable[Submission], people: Iterable[HiddenPerson]
) -> tuple[Submission, ...]:
    hidden = hidden_person_keys(people)
    return tuple(item for item in submissions if (item.platform, item.uid) not in hidden)
