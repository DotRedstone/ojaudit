# ruff: noqa: I001
"""

Module: SQLite Store
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
