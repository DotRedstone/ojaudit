"""
Module: Core / ranking
Description: 从本地提交推导榜单，应用人员标记与管理者策略生成最终排名，并导出文件。
Scope: Core
Notes:
- 数据库没有官方名次与罚时；推导榜单按每人每题赛中最高分求和，始终标注非官方。
- 只统计比赛期间（phase=contest）的提交，赛前与赛后补题不计分。
- 保留输入的排名顺序；剔除后重新连续编号。CLI 与 TUI 共用本模块。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ojaudit.core.config import data_dir
from ojaudit.core.people import HiddenPerson, hidden_person_keys

EXPORT_FORMATS = ("xlsx", "md", "csv", "html")


@dataclass(frozen=True, slots=True)
class RankingOptions:
    cheaters: Literal["drop", "mark"] = "drop"
    suspects: Literal["keep", "mark", "drop"] = "keep"
    managers: Literal["drop", "mark"] = "drop"
    # 一次都没有提交（只报名没做题）的人：保留或剔除。
    inactive: Literal["keep", "drop"] = "keep"

    def __post_init__(self) -> None:
        if self.cheaters not in {"drop", "mark"}:
            raise ValueError("cheaters 必须为 drop 或 mark")
        if self.suspects not in {"keep", "mark", "drop"}:
            raise ValueError("suspects 必须为 keep、mark 或 drop")
        if self.managers not in {"drop", "mark"}:
            raise ValueError("managers 必须为 drop 或 mark")
        if self.inactive not in {"keep", "drop"}:
            raise ValueError("inactive 必须为 keep 或 drop")


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
        if policy.inactive == "drop" and row.get("submissions", 1) == 0:
            continue  # 只报名、一次都没提交
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


def derive_rows(
    platform: str,
    people: Iterable[tuple[str, str]],
    submissions: Iterable[tuple[str, int, float, int, str]],
) -> list[dict[str, Any]]:
    """people 为 (uid, 姓名)，submissions 为 (uid, 题号, 得分, 提交时间, 阶段)。

    每人每题取赛中最高分（同分取最早），总分降序；同分时最后一次得分越早越靠前。
    """
    best: dict[tuple[str, int], tuple[float, int]] = {}
    attempts: dict[tuple[str, int], int] = {}
    counts: dict[str, int] = {}
    for uid, problem, score, time, phase in submissions:
        counts[str(uid)] = counts.get(str(uid), 0) + 1
        if phase != "contest":
            continue
        key = (str(uid), int(problem))
        attempts[key] = attempts.get(key, 0) + 1
        old = best.get(key)
        if old is None or score > old[0] or (score == old[0] and time < old[1]):
            best[key] = (float(score), int(time))
    # 每人每题：赛中最高分、首次达到该分的时间、赛中提交次数（导出表格的可选列）。
    detail: dict[str, dict[int, dict[str, Any]]] = {}
    for (uid, problem), (score, time) in best.items():
        detail.setdefault(uid, {})[problem] = {
            "score": score,
            "time": time,
            "attempts": attempts[(uid, problem)],
        }
    rows = []
    for uid, name in people:
        problems = detail.get(str(uid), {})
        rows.append(
            {
                "platform": platform,
                "uid": str(uid),
                "name": name,
                "score": sum(item["score"] for item in problems.values()),
                "submit_time": max((item["time"] for item in problems.values()), default=0),
                "submissions": counts.get(str(uid), 0),
                "problems": problems,
            }
        )
    # 同分时最后一次得分越早越靠前；0 分时有提交的排在只报名的人前面。
    rows.sort(
        key=lambda row: (
            -row["score"],
            row["submit_time"] if row["score"] else 0,
            row["submissions"] == 0,
            row["uid"],
        )
    )
    return [{**row, "rank": index} for index, row in enumerate(rows, 1)]


def contest_layout(store: Any, platform: str, contest_id: str) -> tuple[list[int], int | None, str]:
    """比赛的题号列表、开始时间（毫秒）与名称，供导出表格生成各题列、相对用时与标题。"""
    problems = [
        int(row[0])
        for row in store.connection.execute(
            "SELECT problem_index FROM problems WHERE platform=? AND contest_id=? "
            "UNION SELECT problem_index FROM submissions WHERE platform=? AND contest_id=? "
            "ORDER BY 1",
            (platform, contest_id, platform, contest_id),
        )
    ]
    row = store.connection.execute(
        "SELECT start_time, name FROM contests WHERE platform=? AND contest_id=?",
        (platform, contest_id),
    ).fetchone()
    start = int(row[0]) if row and row[0] else None
    return problems, start, str(row[1]) if row else contest_id


def contest_ranking(
    store: Any, platform: str, contest_id: str, options: RankingOptions
) -> FinalRanking:
    """从 Store 读取比赛数据并生成最终排名。"""
    if not store.contest_exists(platform, contest_id):
        raise ValueError(f"比赛不存在：{platform}/{contest_id}；请先 collect 或 migrate")
    rows = derive_rows(
        platform,
        store.participants(platform, contest_id),
        (
            (s.uid, s.problem_index, s.score, s.submit_time, s.phase)
            for s in store.submissions(platform, contest_id)
        ),
    )
    marks = {row["uid"]: row["mark"] for row in store.list_person_marks(platform, contest_id)}
    hidden = [HiddenPerson(**person) for person in store.list_hidden_people()]
    return build_final_ranking(rows, marks, hidden, options)


def _safe_part(part: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", part):
        raise ValueError("导出路径的平台与比赛 ID 仅允许字母、数字、下划线和连字符")
    return part


def default_export_path(
    platform: str, contest_id: str, format_name: str, base_dir: Path | None = None
) -> Path:
    """默认导出到 $XDG_DATA_HOME/ojaudit/exports/<平台>/<比赛>/ranking.<格式>。"""
    base = base_dir if base_dir is not None else data_dir() / "exports"
    return base / _safe_part(platform) / _safe_part(contest_id) / f"ranking.{format_name}"


def export_ranking(table: Any, format_name: str, destination: Path) -> Path:
    """table 为 core.ranking_table.RankingTable。"""
    from ojaudit.core.ranking_table import write_table

    if format_name not in EXPORT_FORMATS:
        raise ValueError("仅支持 xlsx/md/csv/html")
    return write_table(table, format_name, destination)
