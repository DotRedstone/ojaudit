"""
Module: Core / ranking
Description: 应用人工人员标记和隐藏人员策略生成最终排名。
Scope: Core
Notes: 保留输入的官方排名顺序；剔除后重新连续编号。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ojaudit.core.people import HiddenPerson, hidden_person_keys


@dataclass(frozen=True, slots=True)
class RankingOptions:
    cheaters: Literal["drop", "mark"] = "drop"
    suspects: Literal["keep", "mark", "drop"] = "keep"
    managers: Literal["drop", "mark"] = "drop"

    def __post_init__(self) -> None:
        if self.cheaters not in {"drop", "mark"}:
            raise ValueError("cheaters 必须为 drop 或 mark")
        if self.suspects not in {"keep", "mark", "drop"}:
            raise ValueError("suspects 必须为 keep、mark 或 drop")
        if self.managers not in {"drop", "mark"}:
            raise ValueError("managers 必须为 drop 或 mark")


@dataclass(frozen=True, slots=True)
class FinalRanking:
    rows: tuple[dict[str, Any], ...]
    options: RankingOptions


def build_final_ranking(
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    person_marks: dict[str, str] | None = None,
    hidden_people: tuple[HiddenPerson, ...] | list[HiddenPerson] = (),
    options: RankingOptions | None = None,
) -> FinalRanking:
    policy = options or RankingOptions()
    marks = person_marks or {}
    hidden = hidden_person_keys(hidden_people)
    ordered = sorted(
        enumerate(rows),
        key=lambda pair: (
            pair[1].get("rank", pair[0] + 1),
            str(pair[1].get("uid", "")),
            pair[0],
        ),
    )
    final_rows: list[dict[str, Any]] = []
    for _, source in ordered:
        row = dict(source)
        uid = str(row.get("uid", ""))
        is_manager = (str(row.get("platform", "")), uid) in hidden
        mark = marks.get(uid, "normal")
        if mark not in {"normal", "suspect", "cheater"}:
            raise ValueError(f"未知人员标记: {mark}")
        if is_manager:
            if policy.managers == "drop":
                continue
            row["person_mark"] = "manager"
        elif mark == "cheater":
            if policy.cheaters == "drop":
                continue
            row["person_mark"] = "cheater"
        elif mark == "suspect":
            if policy.suspects == "drop":
                continue
            if policy.suspects == "mark":
                row["person_mark"] = "suspect"
            else:
                row.pop("person_mark", None)
        else:
            row.pop("person_mark", None)
        final_rows.append(row)
    return FinalRanking(
        rows=tuple({**row, "rank": index} for index, row in enumerate(final_rows, 1)),
        options=policy,
    )
