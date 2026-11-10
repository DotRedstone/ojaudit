"""
Module: TUI / review data
Description: 读取本地证据与提交历史并通过核心 Store 保存人工结论。
Scope: TUI
Notes:
- 查询只访问本地 SQLite；写入限于核心 Store 的人工记录接口。
- 检测结果与人工记录分离，不重新分析或覆盖历史结果。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from ojaudit.core.reviews import DEFAULT_REVIEW_STATUS, finding_key
from ojaudit.core.schema import Contest, is_accepted
from ojaudit.core.store import Store
from ojaudit.tui.data import LocalContests
from ojaudit.tui.ui import level_rank, level_weight


def _items(rows: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


class ReviewData:
    def __init__(self, local: LocalContests, contest: Contest) -> None:
        self.local = local
        self.contest = contest
        self.key = (contest.platform, contest.contest_id)

    def _read(self, statement: str, *args: Any) -> list[dict[str, Any]]:
        connection = self.local._connect()
        if connection is None:
            return []
        try:
            return _items(connection.execute(statement, args).fetchall())
        except sqlite3.OperationalError:
            # 数据库正在被后台任务创建或迁移时按无数据处理。
            return []
        finally:
            connection.close()

    def latest_run(self) -> str | None:
        rows = self._read(
            "SELECT run_id FROM analysis_runs WHERE platform=? AND contest_id=? "
            "ORDER BY created_at DESC, run_id DESC LIMIT 1",
            *self.key,
        )
        return str(rows[0]["run_id"]) if rows else None

    def people(self) -> list[dict[str, Any]]:
        people = self._read(
            "SELECT uid, name FROM participants WHERE platform=? AND contest_id=? "
            "ORDER BY name, uid",
            *self.key,
        )
        hidden = {
            str(row["uid"])
            for row in self._read(
                "SELECT uid FROM hidden_people WHERE platform=?", self.contest.platform
            )
        }
        marks = {
            row["uid"]: row
            for row in self._read(
                "SELECT uid, mark, note FROM person_marks WHERE platform=? AND contest_id=?",
                *self.key,
            )
        }
        for person in people:
            person["hidden"] = person["uid"] in hidden
            mark = marks.get(person["uid"], {})
            person["mark"] = mark.get("mark", "")
            person["note"] = mark.get("note", "")
        return people

    def person(self, uid: str) -> dict[str, Any]:
        return next(
            (item for item in self.people() if item["uid"] == uid),
            {"uid": uid, "name": uid, "hidden": False, "mark": "", "note": ""},
        )

    def problems(self) -> list[dict[str, Any]]:
        return self._read(
            "SELECT problem_index, problem_id, title FROM problems "
            "WHERE platform=? AND contest_id=? "
            "UNION ALL "
            "SELECT DISTINCT s.problem_index, CAST(s.problem_index AS TEXT), "
            "'题 ' || s.problem_index FROM submissions AS s "
            "WHERE s.platform=? AND s.contest_id=? AND NOT EXISTS "
            "(SELECT 1 FROM problems AS p WHERE p.platform=s.platform "
            "AND p.contest_id=s.contest_id AND p.problem_index=s.problem_index) "
            "ORDER BY problem_index",
            *self.key,
            *self.key,
        )

    def submissions(
        self, uid: str | None = None, problem_index: int | None = None
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT s.submission_id, s.uid, p.name, s.problem_index, s.language, "
            "s.verdict, s.score, s.submit_time, s.phase, s.code "
            "FROM submissions AS s LEFT JOIN participants AS p ON "
            "p.platform=s.platform AND p.contest_id=s.contest_id AND p.uid=s.uid "
            "WHERE s.platform=? AND s.contest_id=?"
        )
        args: list[Any] = list(self.key)
        if uid is not None:
            sql += " AND s.uid=?"
            args.append(uid)
        if problem_index is not None:
            sql += " AND s.problem_index=?"
            args.append(problem_index)
        sql += " ORDER BY s.submit_time, s.submission_id"
        return self._read(sql, *args)

    def representative(
        self, uid: str, problem_index: int, language: str | None = None
    ) -> dict[str, Any] | None:
        items = self.submissions(uid, problem_index)
        if language is not None:
            items = [item for item in items if item["language"] == language]
        if not items:
            return None
        return min(
            items,
            key=lambda row: (
                -float(row["score"]),
                -len(row["code"]),
                int(row["submit_time"]),
                str(row["submission_id"]),
            ),
        )

    def representatives(self, problem_index: int, order: str = "time") -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for person in self.people():
            item = self.representative(person["uid"], problem_index)
            if item is not None:
                item["hidden"] = person["hidden"]
                item["mark"] = person["mark"]
                entries.append(item)
        if order == "name":
            return sorted(entries, key=lambda row: (row["name"] or "", row["uid"]))
        if order == "findings":
            counts = self.finding_counts(problem_index)
            return sorted(entries, key=lambda row: (-counts.get(row["uid"], 0), row["uid"]))
        return sorted(
            entries,
            key=lambda row: (
                0 if is_accepted(row["verdict"]) else 1,
                int(row["submit_time"]),
                row["uid"],
            ),
        )

    def finding_counts(self, problem_index: int) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.findings():
            if item["is_stale"] or item["problem_index"] != problem_index:
                continue
            for uid in (item["uid_a"], item["uid_b"]):
                result[uid] = result.get(uid, 0) + 1
        return result

    def findings(self) -> list[dict[str, Any]]:
        run = self.latest_run()
        current = (
            self._read(
                "SELECT run_id, uid_a, uid_b, problem_index, language, verdict_level, "
                "scores, reasons FROM findings WHERE run_id=? "
                "ORDER BY problem_index, uid_a, uid_b, language",
                run,
            )
            if run
            else []
        )
        reviews = self._read(
            "SELECT run_id, uid_a, uid_b, problem_index, language, status, note "
            "FROM finding_reviews WHERE platform=? AND contest_id=? "
            "ORDER BY updated_at DESC, run_id DESC",
            *self.key,
        )
        current_keys = {finding_key(item) for item in current}
        reviewed = {}
        for row in reviews:
            reviewed.setdefault(finding_key(row), row)
        for item in current:
            review = reviewed.get(finding_key(item), {})
            item["status"] = review.get("status", DEFAULT_REVIEW_STATUS)
            item["note"] = review.get("note", "")
            item["is_stale"] = False
            item["scores"] = _decode(item["scores"])
            item["reasons"] = _decode(item["reasons"])
        # 高等级优先复核；同等级保持题号与选手顺序，列表和证据翻页共用同一顺序。
        current.sort(key=lambda item: level_rank(item["verdict_level"]))
        # 历史人工结论仅作只读失效提示，不把其他轮次的复核误判为当前复核。
        stale: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int, str]] = set()
        for row in reviews:
            key = finding_key(row)
            if key in current_keys or key in seen:
                continue
            seen.add(key)
            stale.append(
                {
                    **row,
                    "verdict_level": "历史记录",
                    "scores": {},
                    "reasons": ["当前分析轮次已无此线索"],
                    "is_stale": True,
                }
            )
        return current + stale

    def mark(self, uid: str, mark: str, note: str) -> None:
        if self.person(uid)["hidden"]:
            raise ValueError("管理者不可被标记为参赛选手")
        with Store(self.local.db_path) as store:
            store.put_person_mark(*self.key, uid, mark, note, datetime.now(UTC).isoformat())

    def review(self, finding: dict[str, Any], status: str, note: str) -> None:
        if finding["is_stale"]:
            raise ValueError("不能修改已失效线索")
        with Store(self.local.db_path) as store:
            store.put_finding_review(
                finding["run_id"],
                finding["uid_a"],
                finding["uid_b"],
                int(finding["problem_index"]),
                finding["language"],
                status,
                note,
                datetime.now(UTC).isoformat(),
                platform=self.contest.platform,
                contest_id=self.contest.contest_id,
            )


def _decode(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def pair_key(row: dict[str, Any]) -> tuple[str, str]:
    left, right = sorted((str(row["uid_a"]), str(row["uid_b"])))
    return left, right


def pair_scores(findings: list[dict[str, Any]]) -> dict[tuple[str, str], tuple[int, int]]:
    """每对选手的总嫌疑度（实锤 3、中偏强 2、存疑 1）与涉及的线索数，只计当前轮次。

    同一对选手在多道题上相似时嫌疑叠加，便于把他们的线索排在一起优先处理。
    """
    totals: dict[tuple[str, str], tuple[int, int]] = {}
    for row in findings:
        if row.get("is_stale"):
            continue
        score, count = totals.get(pair_key(row), (0, 0))
        totals[pair_key(row)] = (score + level_weight(row["verdict_level"]), count + 1)
    return totals
