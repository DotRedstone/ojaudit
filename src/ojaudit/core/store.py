# ruff: noqa: I001
"""

Module: Core / store
Description: 管理本地审查数据库及其版本迁移。
Scope: Core

Notes:
- 数据库仅由核心层写入；插件不得直接持有连接。
- 迁移使用事务，失败时回滚，不删除用户数据。
"""

import json
import pathlib
import sqlite3
import typing


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


class Store:
    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> typing.Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def migrate(self) -> None:
        from ojaudit.core.schema import SCHEMA_VERSION

        with self.connection:
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
                self.connection.executescript(script)
                self.connection.execute("DELETE FROM schema_version")
                self.connection.execute("INSERT INTO schema_version VALUES (?)", (version,))

    def execute(self, sql: str, parameters: tuple[typing.Any, ...] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, parameters)

    def upsert_platform(self, platform: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO platforms(platform) VALUES (?)", (platform,)
            )

    def put_contest(
        self,
        platform: str,
        contest_id: str,
        name: str,
        raw_meta: dict[str, typing.Any] | None = None,
    ) -> None:
        self.upsert_platform(platform)
        with self.connection:
            self.connection.execute(
                """INSERT INTO contests(platform, contest_id, name, raw_meta)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(platform, contest_id) DO UPDATE SET
                   name=excluded.name, raw_meta=excluded.raw_meta""",
                (platform, contest_id, name, json.dumps(raw_meta or {}, ensure_ascii=False)),
            )

    def put_hidden_person(self, platform: str, uid: str, nickname: str = "") -> None:
        if not platform or not uid:
            raise ValueError("隐藏人员必须提供 platform 和 uid")
        with self.connection:
            self.connection.execute(
                """INSERT INTO hidden_people(platform, uid, nickname) VALUES (?, ?, ?)
                   ON CONFLICT(platform, uid) DO UPDATE SET nickname=excluded.nickname""",
                (platform, uid, nickname),
            )

    def remove_hidden_person(self, platform: str, uid: str) -> None:
        with self.connection:
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
        if mark not in {"normal", "suspect", "cheater"}:
            raise ValueError("人员标记必须为 normal、suspect 或 cheater")
        if not all((platform, contest_id, uid, updated_at)):
            raise ValueError("人员标记的归属键和更新时间不能为空")
        with self.connection:
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
    ) -> None:
        if status not in {"已核查", "无需跟进", "需进一步核实"}:
            raise ValueError("线索复核状态无效")
        if not all((run_id, uid_a, uid_b, language, updated_at)):
            raise ValueError("线索复核的归属键和更新时间不能为空")
        left, right = sorted((uid_a, uid_b))
        with self.connection:
            self.connection.execute(
                """INSERT INTO finding_reviews(
                       run_id, uid_a, uid_b, problem_index, language, status, note, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, uid_a, uid_b, problem_index, language) DO UPDATE SET
                   status=excluded.status, note=excluded.note, updated_at=excluded.updated_at""",
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
