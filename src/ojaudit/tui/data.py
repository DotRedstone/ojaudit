"""
Module: TUI / data
Description: 从本地数据库只读加载比赛及总览统计。
Scope: TUI
Notes:
- 不创建或迁移数据库；缺失数据库视为空数据。
- 不触发数据源插件或网络请求。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ojaudit.core.config import data_dir
from ojaudit.core.filters import ContestFilter, evaluate_contest, load_contest_filter
from ojaudit.core.schema import Contest


@dataclass(frozen=True, slots=True)
class ContestEntry:
    contest: Contest
    visible: bool


@dataclass(frozen=True, slots=True)
class ContestStats:
    findings: int
    participants: int
    problems: int
    submissions: int


class LocalContests:
    def __init__(
        self,
        db_path: str | Path | None = None,
        contest_filter: ContestFilter | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else data_dir() / "ojaudit.sqlite"
        self.contest_filter = contest_filter

    def _connect(self) -> sqlite3.Connection | None:
        if not self.db_path.is_file():
            return None
        connection = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def toggle_excluded(self, contest: Contest) -> bool:
        """手动剔除 / 恢复比赛（写入配置）；返回现在是否被剔除。"""
        from ojaudit.core.filters import toggle_excluded

        updated, removed = toggle_excluded(contest)
        if self.contest_filter is not None:
            from dataclasses import replace

            self.contest_filter = replace(self.contest_filter, excluded=updated.excluded)
        return removed

    def list_contests(self, show_all: bool = False) -> list[ContestEntry]:
        connection = self._connect()
        if connection is None:
            return []
        try:
            rows = connection.execute(
                "SELECT platform, contest_id, name, start_time, end_time "
                "FROM contests ORDER BY start_time IS NULL, start_time DESC, name, contest_id"
            ).fetchall()
        except sqlite3.OperationalError:
            # 后台任务刚创建数据库、尚未完成迁移时，按空库处理。
            return []
        finally:
            connection.close()
        rules = self.contest_filter
        if rules is None:
            rules = load_contest_filter()
        result: list[ContestEntry] = []
        for row in rows:
            contest = Contest(**dict(row))
            visible = evaluate_contest(contest, rules).visible
            if show_all or visible:
                result.append(ContestEntry(contest, visible))
        return result

    def stats(self, contest: Contest) -> ContestStats:
        connection = self._connect()
        if connection is None:
            return ContestStats(0, 0, 0, 0)
        try:
            return self._stats(connection, contest)
        except sqlite3.OperationalError:
            return ContestStats(0, 0, 0, 0)
        finally:
            connection.close()

    @staticmethod
    def _stats(connection: sqlite3.Connection, contest: Contest) -> ContestStats:
        key = (contest.platform, contest.contest_id)

        def count(table: str) -> int:
            return int(
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE platform=? AND contest_id=?", key
                ).fetchone()[0]
            )

        findings = int(
            connection.execute(
                "SELECT count(*) FROM findings WHERE run_id = "
                "(SELECT run_id FROM analysis_runs WHERE platform=? AND contest_id=? "
                "ORDER BY created_at DESC, run_id DESC LIMIT 1)",
                key,
            ).fetchone()[0]
        )
        return ContestStats(
            findings,
            count("participants"),
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM ("
                    "SELECT problem_index FROM problems WHERE platform=? AND contest_id=? "
                    "UNION SELECT problem_index FROM submissions "
                    "WHERE platform=? AND contest_id=?)",
                    (*key, *key),
                ).fetchone()[0]
            ),
            count("submissions"),
        )
