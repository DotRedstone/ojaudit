"""
Module: Core / ingest
Description: 把数据源包、JSON 导入包和旧版 nowcoder-collect 数据库转换为标准对象并写入 Store。
Scope: Core
Notes:
- 先完整解析和校验，再在一个事务中写入；任何错误都不会留下部分数据。
- 旧库只读打开，拒绝未知结构而不猜测列含义。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ojaudit.core.schema import (
    Contest,
    Participant,
    Problem,
    Submission,
    language_bucket,
    parse_problem_index,
    validate_submission,
)
from ojaudit.core.store import Store, placeholder_title


def _problems_from_submissions(
    platform: str, contest_id: str, rows: Iterable[tuple[int, str] | tuple[int, str, str]]
) -> list[Problem]:
    """从提交中出现的题号、（可选）标题与平台题目 ID 推导题目；有值者优先。"""
    titles: dict[int, str] = {}
    ids: dict[int, str] = {}
    for row in rows:
        index, title = row[0], row[1]
        if title or index not in titles:
            titles[index] = title or titles.get(index, "")
        if len(row) > 2 and row[2]:
            ids[index] = str(row[2])
    return [
        Problem(
            platform,
            contest_id,
            index,
            ids.get(index, str(index)),
            title or placeholder_title(index),
        )
        for index, title in sorted(titles.items())
    ]


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def import_bundle(store: Store, bundle: Any) -> Contest:
    """写入数据源插件返回的标准对象包。"""
    store.import_contest(bundle.contest, bundle.participants, bundle.problems, bundle.submissions)
    return bundle.contest


def import_json(store: Store, source: Path) -> Contest:
    """导入合成/旧版 JSON 包：{contest, participants, submissions}。"""
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("导入文件根节点必须是 JSON 对象")
    info = raw.get("contest", raw)
    platform = str(info.get("platform", raw.get("platform", "synthetic")))
    cid = str(info.get("contest_id", raw.get("contest_id", "")))
    name = str(info.get("name", raw.get("name", "")))
    if not all((platform, cid, name)):
        raise ValueError("导入包缺少比赛平台、ID 或名称")
    people = raw.get("participants", [])
    submissions = raw.get("submissions", [])
    if not isinstance(people, list) or not isinstance(submissions, list):
        raise TypeError("participants 和 submissions 必须是数组")
    parsed = []
    for item in submissions:
        row = Submission(
            platform,
            cid,
            str(item["submission_id"]),
            str(item["uid"]),
            parse_problem_index(item["problem_index"]),
            language_bucket(str(item["language"])),
            str(item.get("verdict", "")),
            float(item.get("score", 0)),
            int(item.get("submit_time", 0)),
            str(item.get("phase", "contest")),
            str(item.get("code", "")),
        )
        validate_submission(row)
        parsed.append(row)
    contest = Contest(platform, cid, name)
    store.import_contest(
        contest,
        [Participant(platform, cid, str(p["uid"]), str(p.get("name", p["uid"]))) for p in people],
        _problems_from_submissions(
            platform,
            cid,
            (
                (row.problem_index, str(item.get("problem_title") or "").strip())
                for row, item in zip(parsed, submissions)
            ),
        ),
        parsed,
    )
    return contest


_LEGACY_COLUMNS = {
    "contests": {"contest_id", "name"},
    "submissions": {
        "submission_id",
        "contest_id",
        "student",
        "student_id",
        "problem_index",
        "language",
        "phase",
        "code",
    },
}


def _read_legacy(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not source.is_file():
        raise FileNotFoundError(source)
    old = sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)
    old.row_factory = sqlite3.Row
    try:
        tables = {
            row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not set(_LEGACY_COLUMNS) <= tables:
            raise ValueError("旧库缺少 contests/submissions 表")
        for table, names in _LEGACY_COLUMNS.items():
            columns = {row["name"] for row in old.execute(f"PRAGMA table_info({table})")}
            if not names <= columns:
                raise ValueError(f"旧库 {table} 列结构不匹配")
        contests = [dict(row) for row in old.execute("SELECT * FROM contests")]
        submissions = [dict(row) for row in old.execute("SELECT * FROM submissions")]
    finally:
        old.close()
    return contests, submissions


def _read_reviews(path: Path) -> list[dict[str, Any]]:
    """reviews.json 只接受明确的复核记录数组。"""
    data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError("reviews.json 必须是复核记录数组")
    rows = []
    for row in data:
        if not isinstance(row, dict):
            raise TypeError("复核记录必须是对象")
        rows.append(
            {
                "run_id": str(row["run_id"]),
                "uid_a": str(row["uid_a"]),
                "uid_b": str(row["uid_b"]),
                "problem_index": int(row["problem_index"]),
                "language": str(row["language"]),
                "status": str(row["status"]),
                "note": str(row.get("note", "")),
                "updated_at": str(row["updated_at"]),
            }
        )
    return rows


@dataclass(frozen=True, slots=True)
class MigrationReport:
    submissions: int
    reviews: int = 0
    # 无法唯一确定比赛的复核记录：(run_id, uid_a, uid_b, 题号, 原因)
    skipped_reviews: tuple[tuple[str, str, str, int, str], ...] = ()


def _review_contests(
    submissions: Iterable[Submission],
) -> dict[tuple[str, int, str], set[str]]:
    """(UID, 题号, 语言) → 出现过该提交的比赛集合，用于推断复核记录属于哪场比赛。"""
    index: dict[tuple[str, int, str], set[str]] = {}
    for item in submissions:
        index.setdefault((item.uid, item.problem_index, item.language), set()).add(item.contest_id)
    return index


def migrate_nowcoder(store: Store, source: Path, reviews: Path | None = None) -> MigrationReport:
    """只读导入 nowcoder-collect 旧库。

    reviews.json 不含比赛 ID：用双方 UID、题号与语言在旧库提交中定位比赛，
    只有恰好一场比赛同时包含双方该题该语言的提交时才导入，其余在报告中列出。
    """
    contests, rows = _read_legacy(source.expanduser())
    review_rows = _read_reviews(reviews) if reviews is not None else []

    by_contest: dict[str, dict[str, Any]] = {
        str(c["contest_id"]): {
            "name": str(c["name"] or c["contest_id"]),
            "start": _int_or_none(c.get("start_time")),
            "end": _int_or_none(c.get("end_time")),
            "rows": [],
        }
        for c in contests
    }
    for row in rows:
        cid = str(row["contest_id"])
        by_contest.setdefault(cid, {"name": cid, "start": None, "end": None, "rows": []})[
            "rows"
        ].append(row)

    plans = []
    every_submission: list[Submission] = []
    for cid, entry in sorted(by_contest.items()):
        names: dict[str, str] = {}
        parsed = []
        titles = []
        for row in entry["rows"]:
            uid = str(row["student_id"] if row["student_id"] is not None else row["student"])
            index = parse_problem_index(row["problem_index"])
            item = Submission(
                "nowcoder",
                cid,
                str(row["submission_id"]),
                uid,
                index,
                language_bucket(str(row["language"] or "")),
                str(row.get("verdict") or ""),
                float(row.get("score") or 0),
                int(row.get("submit_time") or 0),
                str(row.get("phase") or "contest"),
                str(row.get("code") or ""),
            )
            validate_submission(item)
            parsed.append(item)
            names[uid] = str(row["student"] or uid)
            titles.append(
                (
                    index,
                    str(row.get("problem_title") or "").strip(),
                    str(row.get("problem_id") or ""),
                )
            )
        plans.append(
            (
                Contest("nowcoder", cid, entry["name"], entry["start"], entry["end"]),
                [Participant("nowcoder", cid, uid, name) for uid, name in sorted(names.items())],
                _problems_from_submissions("nowcoder", cid, titles),
                parsed,
            )
        )
        every_submission.extend(parsed)

    located = _review_contests(every_submission)
    placed = []
    skipped = []
    for review in review_rows:
        language = language_bucket(review["language"])
        key = (review["run_id"], review["uid_a"], review["uid_b"], review["problem_index"])
        candidates = located.get(
            (review["uid_a"], review["problem_index"], language), set()
        ) & located.get((review["uid_b"], review["problem_index"], language), set())
        if len(candidates) == 1:
            placed.append({**review, "language": language, "contest_id": candidates.pop()})
        else:
            reason = "旧库中找不到双方的对应提交" if not candidates else "多场比赛都符合"
            skipped.append((*key, reason))

    with store.transaction():
        for plan in plans:
            store.import_contest(*plan)
        for review in placed:
            store.put_finding_review(**review, platform="nowcoder", overwrite=False)
    return MigrationReport(len(every_submission), len(placed), tuple(skipped))
