"""
Module: Core / store
Description: 管理本地审查数据库、版本迁移与全部写入。
Scope: Core

Notes:
- 数据库仅由核心层写入；插件与界面只调用这里的方法，不拼写入 SQL。
- 连接处于自动提交模式，写入统一经 transaction()；嵌套调用并入最外层事务，
  任何一步失败整体回滚，避免部分导入。
- 迁移在单个事务内执行，失败时回滚，不删除用户数据。
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import sqlite3
import typing
from collections.abc import Generator, Iterable

from ojaudit.core.schema import (
    SCHEMA_VERSION,
    Contest,
    Participant,
    Problem,
    Submission,
    validate_submission,
)

_MIGRATIONS = {
    1: """
    CREATE TABLE platforms (
        platform TEXT PRIMARY KEY
    );
    CREATE TABLE contests (
        platform TEXT NOT NULL, contest_id TEXT NOT NULL, name TEXT NOT NULL,
        start_time INTEGER, end_time INTEGER, raw_meta TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (platform, contest_id),
        FOREIGN KEY (platform) REFERENCES platforms(platform)
    );
    CREATE TABLE problems (
        platform TEXT NOT NULL, contest_id TEXT NOT NULL, problem_index INTEGER NOT NULL,
        problem_id TEXT NOT NULL, title TEXT NOT NULL, full_score REAL,
        PRIMARY KEY (platform, contest_id, problem_index),
        FOREIGN KEY (platform, contest_id) REFERENCES contests(platform, contest_id)
    );
    CREATE TABLE participants (
        platform TEXT NOT NULL, contest_id TEXT NOT NULL, uid TEXT NOT NULL, name TEXT NOT NULL,
        PRIMARY KEY (platform, contest_id, uid),
        FOREIGN KEY (platform, contest_id) REFERENCES contests(platform, contest_id)
    );
    CREATE TABLE submissions (
        platform TEXT NOT NULL, contest_id TEXT NOT NULL, submission_id TEXT NOT NULL,
        uid TEXT NOT NULL, problem_index INTEGER NOT NULL, language TEXT NOT NULL,
        verdict TEXT NOT NULL, score REAL NOT NULL, submit_time INTEGER NOT NULL,
        phase TEXT NOT NULL, code TEXT NOT NULL, raw_meta TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (platform, contest_id, submission_id),
        FOREIGN KEY (platform, contest_id, uid) REFERENCES participants(platform, contest_id, uid)
    );
    CREATE TABLE analysis_runs (
        run_id TEXT PRIMARY KEY, platform TEXT NOT NULL, contest_id TEXT NOT NULL,
        plugin_set TEXT NOT NULL, created_from TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE findings (
        run_id TEXT NOT NULL, uid_a TEXT NOT NULL, uid_b TEXT NOT NULL,
        problem_index INTEGER NOT NULL, language TEXT NOT NULL, verdict_level TEXT NOT NULL,
        scores TEXT NOT NULL, reasons TEXT NOT NULL,
        PRIMARY KEY (run_id, uid_a, uid_b, problem_index, language)
    );
    CREATE TABLE single_signals (
        run_id TEXT NOT NULL, uid TEXT NOT NULL, problem_index INTEGER NOT NULL,
        plugin TEXT NOT NULL, signal TEXT NOT NULL, value REAL NOT NULL, reason TEXT NOT NULL,
        PRIMARY KEY (run_id, uid, problem_index, plugin, signal)
    );
    CREATE TABLE finding_reviews (
        run_id TEXT NOT NULL, uid_a TEXT NOT NULL, uid_b TEXT NOT NULL,
        problem_index INTEGER NOT NULL, language TEXT NOT NULL,
        status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
        PRIMARY KEY (run_id, uid_a, uid_b, problem_index, language)
    );
    CREATE TABLE person_marks (
        platform TEXT NOT NULL, contest_id TEXT NOT NULL, uid TEXT NOT NULL,
        mark TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
        PRIMARY KEY (platform, contest_id, uid)
    );
    """,
    2: """
    CREATE TABLE hidden_people (
        platform TEXT NOT NULL, uid TEXT NOT NULL, nickname TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (platform, uid)
    );
    """,
}

REVIEW_STATUSES = frozenset({"已核查", "无需跟进", "需进一步核实"})
PERSON_MARKS = frozenset({"normal", "suspect", "cheater"})


def placeholder_title(index: int) -> str:
    return f"题 {index}"


class Store:
    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 自动提交模式：事务边界只由 transaction() 决定，不受 sqlite3 隐式 BEGIN 影响。
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self._depth = 0
        self.migrate()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> typing.Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextlib.contextmanager
    def transaction(self) -> Generator[None]:
        """开启写事务；嵌套调用只计数，由最外层统一提交或回滚。"""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self.connection.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")
        finally:
            self._depth = 0

    def migrate(self) -> None:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = self.connection.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0
        if current > SCHEMA_VERSION:
            raise RuntimeError("数据库版本高于当前程序，拒绝降级打开")
        for version in range(current + 1, SCHEMA_VERSION + 1):
            script = _MIGRATIONS.get(version)
            if script is None:
                raise RuntimeError(f"缺少 schema migration: {version}")
            try:
                self.connection.executescript(
                    f"BEGIN IMMEDIATE;\n{script}\nDELETE FROM schema_version;\n"
                    f"INSERT INTO schema_version VALUES ({int(version)});\nCOMMIT;"
                )
            except sqlite3.Error:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    def execute(self, sql: str, parameters: tuple[typing.Any, ...] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, parameters)

    # ── 比赛数据 ────────────────────────────────────────────

    def upsert_platform(self, platform: str) -> None:
        with self.transaction():
            self.connection.execute(
                "INSERT OR IGNORE INTO platforms(platform) VALUES (?)", (platform,)
            )

    def put_contest(
        self,
        platform: str,
        contest_id: str,
        name: str,
        raw_meta: dict[str, typing.Any] | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> None:
        with self.transaction():
            self.upsert_platform(platform)
            self.connection.execute(
                """INSERT INTO contests(platform, contest_id, name, start_time, end_time, raw_meta)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(platform, contest_id) DO UPDATE SET
                   name=excluded.name, raw_meta=excluded.raw_meta,
                   start_time=COALESCE(excluded.start_time, contests.start_time),
                   end_time=COALESCE(excluded.end_time, contests.end_time)""",
                (
                    platform,
                    contest_id,
                    name,
                    start_time,
                    end_time,
                    json.dumps(raw_meta or {}, ensure_ascii=False),
                ),
            )

    def put_participants(self, people: Iterable[Participant], *, keep_names: bool = False) -> None:
        """keep_names=True 时只补缺失的人员，不覆盖已有姓名（用于提交里出现的 UID）。"""
        action = "NOTHING" if keep_names else "UPDATE SET name=excluded.name"
        with self.transaction():
            self.connection.executemany(
                f"""INSERT INTO participants(platform, contest_id, uid, name) VALUES (?, ?, ?, ?)
                    ON CONFLICT(platform, contest_id, uid) DO {action}""",
                [(p.platform, p.contest_id, p.uid, p.name) for p in people],
            )

    def put_problems(self, problems: Iterable[Problem]) -> None:
        """已有真实标题时，不被占位标题（空或「题 N」）覆盖。"""
        with self.transaction():
            self.connection.executemany(
                """INSERT INTO problems(
                       platform, contest_id, problem_index, problem_id, title, full_score
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(platform, contest_id, problem_index) DO UPDATE SET
                   problem_id=excluded.problem_id,
                   full_score=COALESCE(excluded.full_score, problems.full_score),
                   title=CASE
                       WHEN excluded.title = '' OR excluded.title = ('题 ' || excluded.problem_index)
                       THEN problems.title ELSE excluded.title END""",
                [
                    (p.platform, p.contest_id, p.index, p.problem_id, p.title, p.full_score)
                    for p in problems
                ],
            )

    def put_submissions(self, submissions: Iterable[Submission]) -> None:
        rows = list(submissions)
        for item in rows:
            validate_submission(item)
        with self.transaction():
            self.connection.executemany(
                """INSERT INTO submissions(
                       platform, contest_id, submission_id, uid, problem_index, language,
                       verdict, score, submit_time, phase, code, raw_meta
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(platform, contest_id, submission_id) DO UPDATE SET
                   uid=excluded.uid, problem_index=excluded.problem_index,
                   language=excluded.language, verdict=excluded.verdict,
                   score=excluded.score, submit_time=excluded.submit_time,
                   phase=excluded.phase, code=excluded.code, raw_meta=excluded.raw_meta""",
                [
                    (
                        s.platform,
                        s.contest_id,
                        s.submission_id,
                        s.uid,
                        s.problem_index,
                        s.language,
                        s.verdict,
                        s.score,
                        s.submit_time,
                        s.phase,
                        s.code,
                        json.dumps(s.raw_meta or {}, ensure_ascii=False),
                    )
                    for s in rows
                ],
            )

    def import_contest(
        self,
        contest: Contest,
        participants: Iterable[Participant] = (),
        problems: Iterable[Problem] = (),
        submissions: Iterable[Submission] = (),
    ) -> None:
        """一次事务写入整场比赛；提交中出现但未列出的选手以 UID 作为姓名补齐。"""
        submissions = list(submissions)
        for item in submissions:
            validate_submission(item)
            if (item.platform, item.contest_id) != (contest.platform, contest.contest_id):
                raise ValueError("提交记录不属于当前比赛")
        with self.transaction():
            self.put_contest(
                contest.platform,
                contest.contest_id,
                contest.name,
                contest.raw_meta,
                contest.start_time,
                contest.end_time,
            )
            self.put_participants(participants)
            self.put_participants(
                (Participant(s.platform, s.contest_id, s.uid, s.uid) for s in submissions),
                keep_names=True,
            )
            self.put_problems(problems)
            self.put_submissions(submissions)

    def contest_exists(self, platform: str, contest_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM contests WHERE platform=? AND contest_id=?", (platform, contest_id)
            ).fetchone()
            is not None
        )

    def list_contests(self) -> list[Contest]:
        rows = self.connection.execute(
            "SELECT platform, contest_id, name, start_time, end_time FROM contests "
            "ORDER BY platform, contest_id"
        ).fetchall()
        return [Contest(**dict(row)) for row in rows]

    def submissions(self, platform: str, contest_id: str) -> list[Submission]:
        rows = self.connection.execute(
            """SELECT * FROM submissions WHERE platform=? AND contest_id=?
               ORDER BY submission_id""",
            (platform, contest_id),
        ).fetchall()
        return [
            Submission(
                r["platform"],
                r["contest_id"],
                r["submission_id"],
                r["uid"],
                r["problem_index"],
                r["language"],
                r["verdict"],
                r["score"],
                r["submit_time"],
                r["phase"],
                r["code"],
                json.loads(r["raw_meta"] or "{}"),
            )
            for r in rows
        ]

    # ── 分析结果 ────────────────────────────────────────────

    def save_analysis(
        self,
        run_id: str,
        platform: str,
        contest_id: str,
        plugin_set: str,
        created_from: str,
        created_at: str,
        findings: Iterable[dict[str, typing.Any]],
    ) -> None:
        """写入一次分析运行及其线索；线索的双方 UID 按字典序存储。"""
        rows = []
        for item in findings:
            left, right = sorted((str(item["uid_a"]), str(item["uid_b"])))
            rows.append(
                (
                    run_id,
                    left,
                    right,
                    int(item["problem_index"]),
                    str(item["language"]),
                    str(item["level"]),
                    json.dumps(item.get("scores", {}), ensure_ascii=False),
                    json.dumps(item.get("reasons", []), ensure_ascii=False),
                )
            )
        with self.transaction():
            self.connection.execute(
                """INSERT INTO analysis_runs(
                       run_id, platform, contest_id, plugin_set, created_from, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, platform, contest_id, plugin_set, created_from, created_at),
            )
            self.connection.executemany(
                """INSERT INTO findings(
                       run_id, uid_a, uid_b, problem_index, language,
                       verdict_level, scores, reasons
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

    # ── 人工记录 ────────────────────────────────────────────

    def put_hidden_person(self, platform: str, uid: str, nickname: str = "") -> None:
        if not platform or not uid:
            raise ValueError("隐藏人员必须提供 platform 和 uid")
        with self.transaction():
            self.connection.execute(
                """INSERT INTO hidden_people(platform, uid, nickname) VALUES (?, ?, ?)
                   ON CONFLICT(platform, uid) DO UPDATE SET nickname=excluded.nickname""",
                (platform, uid, nickname),
            )

    def remove_hidden_person(self, platform: str, uid: str) -> None:
        with self.transaction():
            self.connection.execute(
                "DELETE FROM hidden_people WHERE platform=? AND uid=?", (platform, uid)
            )

    def list_hidden_people(self) -> list[dict[str, typing.Any]]:
        rows = self.connection.execute(
            "SELECT platform, uid, nickname FROM hidden_people ORDER BY platform, uid"
        ).fetchall()
        return [dict(row) for row in rows]

    def put_person_mark(
        self,
        platform: str,
        contest_id: str,
        uid: str,
        mark: str,
        note: str = "",
        updated_at: str = "",
    ) -> None:
        if mark not in PERSON_MARKS:
            raise ValueError("人员标记必须为 normal、suspect 或 cheater")
        if not all((platform, contest_id, uid, updated_at)):
            raise ValueError("人员标记的归属键和更新时间不能为空")
        with self.transaction():
            self.connection.execute(
                """INSERT INTO person_marks(platform, contest_id, uid, mark, note, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(platform, contest_id, uid) DO UPDATE SET
                   mark=excluded.mark, note=excluded.note, updated_at=excluded.updated_at""",
                (platform, contest_id, uid, mark, note, updated_at),
            )

    def list_person_marks(self, platform: str, contest_id: str) -> list[dict[str, typing.Any]]:
        rows = self.connection.execute(
            """SELECT platform, contest_id, uid, mark, note, updated_at FROM person_marks
               WHERE platform=? AND contest_id=? ORDER BY uid""",
            (platform, contest_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def put_finding_review(
        self,
        run_id: str,
        uid_a: str,
        uid_b: str,
        problem_index: int,
        language: str,
        status: str,
        note: str = "",
        updated_at: str = "",
        *,
        overwrite: bool = True,
    ) -> None:
        """overwrite=False 时已有复核保持不变（用于导入历史记录）。"""
        if status not in REVIEW_STATUSES:
            raise ValueError("线索复核状态无效")
        if not all((run_id, uid_a, uid_b, language, updated_at)):
            raise ValueError("线索复核的归属键和更新时间不能为空")
        left, right = sorted((uid_a, uid_b))
        action = (
            "UPDATE SET status=excluded.status, note=excluded.note, updated_at=excluded.updated_at"
            if overwrite
            else "NOTHING"
        )
        with self.transaction():
            self.connection.execute(
                f"""INSERT INTO finding_reviews(
                       run_id, uid_a, uid_b, problem_index, language, status, note, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, uid_a, uid_b, problem_index, language) DO {action}""",
                (run_id, left, right, problem_index, language, status, note, updated_at),
            )

    def list_finding_reviews(self, run_id: str) -> list[dict[str, typing.Any]]:
        rows = self.connection.execute(
            """SELECT run_id, uid_a, uid_b, problem_index, language, status, note, updated_at
               FROM finding_reviews WHERE run_id=?
               ORDER BY uid_a, uid_b, problem_index, language""",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
