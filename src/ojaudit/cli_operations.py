"""
Module: CLI / operations
Description: 旧牛客 SQLite 迁移、插件登记与只读采集辅助。
Scope: CLI
Notes: 迁移不修改旧库；第三方插件只登记，不导入执行。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

from ojaudit.core.config import config_dir, load_config
from ojaudit.core.plugins import discover_manifests, parse_manifest
from ojaudit.core.schema import Submission, validate_submission
from ojaudit.plugins.sources.nowcoder import NowcoderSource


def import_bundle(store, bundle) -> None:
    contest = bundle.contest
    with store.connection:
        store.put_contest(contest.platform, contest.contest_id, contest.name)
        for item in bundle.participants:
            store.execute(
                """INSERT INTO participants(platform,contest_id,uid,name)
                   VALUES (?,?,?,?) ON CONFLICT(platform,contest_id,uid)
                   DO UPDATE SET name=excluded.name""",
                (item.platform, item.contest_id, item.uid, item.name),
            )
        for item in bundle.problems:
            store.execute(
                """INSERT INTO problems(platform,contest_id,problem_index,problem_id,title,full_score)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(platform,contest_id,problem_index)
                   DO UPDATE SET problem_id=excluded.problem_id,title=excluded.title,
                   full_score=excluded.full_score""",
                (
                    item.platform,
                    item.contest_id,
                    item.index,
                    item.problem_id,
                    item.title,
                    item.full_score,
                ),
            )
        for item in bundle.submissions:
            validate_submission(item)
            store.execute(
                """INSERT INTO participants(platform,contest_id,uid,name)
                   VALUES (?,?,?,?) ON CONFLICT(platform,contest_id,uid) DO NOTHING""",
                (item.platform, item.contest_id, item.uid, item.uid),
            )
            store.execute(
                """INSERT INTO submissions(platform,contest_id,submission_id,uid,
                   problem_index,language,verdict,score,submit_time,phase,code)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(platform,contest_id,submission_id) DO UPDATE SET
                   uid=excluded.uid,problem_index=excluded.problem_index,
                   language=excluded.language,verdict=excluded.verdict,
                   score=excluded.score,submit_time=excluded.submit_time,
                   phase=excluded.phase,code=excluded.code""",
                (
                    item.platform,
                    item.contest_id,
                    item.submission_id,
                    item.uid,
                    item.problem_index,
                    item.language,
                    item.verdict,
                    item.score,
                    item.submit_time,
                    item.phase,
                    item.code,
                ),
            )


def migrate_nowcoder(store, source: Path, reviews: Path | None = None) -> int:
    """只读旧库；拒绝未知 schema，而不是猜测列含义。"""
    source = source.expanduser()
    if not source.is_file():
        raise FileNotFoundError(source)
    uri = f"file:{source.resolve().as_posix()}?mode=ro"
    old = sqlite3.connect(uri, uri=True)
    old.row_factory = sqlite3.Row
    try:
        tables = {
            row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"contests", "submissions"} <= tables:
            raise ValueError("旧库缺少 contests/submissions 表")
        required = {
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
        for table, names in required.items():
            columns = {row["name"] for row in old.execute(f"PRAGMA table_info({table})")}
            if not names <= columns:
                raise ValueError(f"旧库 {table} 列结构不匹配")
        contests = [dict(row) for row in old.execute("SELECT * FROM contests")]
        submissions = [dict(row) for row in old.execute("SELECT * FROM submissions")]
    finally:
        old.close()
    # 在写库之前验证所有数据，避免部分导入。
    prepared = []
    names = {}
    problem_titles = {}
    for row in submissions:
        cid = str(row["contest_id"])
        uid = str(row["student_id"] if row["student_id"] is not None else row["student"])
        problem = str(row["problem_index"]).strip().upper()
        index = int(problem) if problem.isdigit() else ord(problem) - ord("A")
        title = str(row.get("problem_title") or "").strip()
        problem_titles.setdefault((cid, index), title or f"题 {index}")
        if title:
            problem_titles[(cid, index)] = title
        lang = str(row["language"] or "").lower()
        language = (
            "cpp"
            if "++" in lang or "cpp" in lang
            else (
                "python"
                if "python" in lang or "pypy" in lang
                else ("java" if "java" in lang else "other")
            )
        )
        item = Submission(
            "nowcoder",
            cid,
            str(row["submission_id"]),
            uid,
            index,
            language,
            str(row.get("verdict") or ""),
            float(row.get("score") or 0),
            int(row.get("submit_time") or 0),
            str(row.get("phase") or "contest"),
            str(row.get("code") or ""),
        )
        validate_submission(item)
        prepared.append(item)
        names[(cid, uid)] = str(row["student"] or uid)
    # reviews.json 的历史格式不在旧仓库中定义；仅接收可核验的明确格式。
    review_rows = []
    if reviews is not None:
        data = json.loads(reviews.expanduser().read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise TypeError("reviews.json 必须是复核记录数组")
        for row in data:
            if not isinstance(row, dict):
                raise TypeError("复核记录必须是对象")
            review_rows.append(
                (
                    str(row["run_id"]),
                    str(row["uid_a"]),
                    str(row["uid_b"]),
                    int(row["problem_index"]),
                    str(row["language"]),
                    str(row["status"]),
                    str(row.get("note", "")),
                    str(row["updated_at"]),
                )
            )
    with store.connection:
        for row in contests:
            cid = str(row["contest_id"])
            store.put_contest("nowcoder", cid, str(row["name"] or cid))
        for (cid, uid), name in sorted(names.items()):
            store.execute(
                """INSERT INTO participants(platform,contest_id,uid,name)
                   VALUES (?,?,?,?) ON CONFLICT(platform,contest_id,uid)
                   DO UPDATE SET name=excluded.name""",
                ("nowcoder", cid, uid, name),
            )
        for (cid, index), title in sorted(problem_titles.items()):
            store.execute(
                """INSERT INTO problems(platform,contest_id,problem_index,problem_id,title,full_score)
                   VALUES (?,?,?,?,?,NULL)
                   ON CONFLICT(platform,contest_id,problem_index) DO UPDATE SET
                   title=CASE WHEN problems.title='' OR problems.title=('题 ' || problems.problem_index)
                              THEN excluded.title ELSE problems.title END""",
                ("nowcoder", cid, index, str(index), title),
            )
        for item in prepared:
            store.execute(
                """INSERT INTO submissions(platform,contest_id,submission_id,uid,
                   problem_index,language,verdict,score,submit_time,phase,code)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(platform,contest_id,submission_id) DO UPDATE SET
                   uid=excluded.uid,problem_index=excluded.problem_index,
                   language=excluded.language,verdict=excluded.verdict,
                   score=excluded.score,submit_time=excluded.submit_time,
                   phase=excluded.phase,code=excluded.code""",
                (
                    item.platform,
                    item.contest_id,
                    item.submission_id,
                    item.uid,
                    item.problem_index,
                    item.language,
                    item.verdict,
                    item.score,
                    item.submit_time,
                    item.phase,
                    item.code,
                ),
            )
        for row in review_rows:
            store.execute(
                """INSERT INTO finding_reviews(run_id,uid_a,uid_b,problem_index,
                   language,status,note,updated_at) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(run_id,uid_a,uid_b,problem_index,language) DO NOTHING""",
                row,
            )
    return len(prepared)


def cookie_file() -> Path:
    return config_dir() / "nowcoder.cookie"


def save_cookie(cookie: str) -> None:
    if not cookie.strip() or "\n" in cookie or "\r" in cookie:
        raise ValueError("Cookie 无效")
    path = cookie_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(cookie.strip())
    os.chmod(path, 0o600)


def nowcoder_source():
    settings = load_config().get("nowcoder", {})
    if not isinstance(settings, dict):
        raise TypeError("nowcoder 配置必须是表")
    if cookie_file().is_file():
        settings["cookie"] = cookie_file().read_text(encoding="utf-8").strip()
    return NowcoderSource(settings)


def plugin_registry() -> Path:
    return config_dir() / "plugins.json"


def plugins_command(action: str, spec: str | None = None) -> None:
    path = plugin_registry()
    registered = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if action == "list":
        for name, item in sorted(registered.items()):
            print(f"{name}\t{item['version']}\t{'enabled' if item['enabled'] else 'disabled'}")
        return
    if action == "install":
        if not spec or "@" not in spec:
            raise ValueError("install 需要 <git-url>@<rev>")
        url, rev = spec.rsplit("@", 1)
        if not re.fullmatch(r"[0-9a-f]{7,40}", rev):
            raise ValueError("必须固定 Git commit SHA")
        # 安全地使用临时目录检查 manifest，不执行插件代码或安装依赖。
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                ["git", "clone", "--quiet", "--no-checkout", "--", url, directory],
                check=True,
                timeout=60,
            )
            subprocess.run(
                ["git", "-C", directory, "checkout", "--detach", rev],
                check=True,
                timeout=30,
                capture_output=True,
            )
            manifests = discover_manifests(directory)
            root = Path(directory) / "plugin.toml"
            if root.is_file():
                manifests.append(parse_manifest(root.read_text(encoding="utf-8"), str(root)))
            if not manifests:
                raise ValueError("仓库未找到 plugin.toml")
            for manifest in manifests:
                registered[manifest.name] = {
                    "version": manifest.version,
                    "origin": f"{url}@{rev}",
                    "kind": manifest.kind,
                    "enabled": False,
                }
    else:
        if not spec or spec not in registered:
            raise ValueError("插件尚未登记")
        registered[spec]["enabled"] = action == "enable"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(registered, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    print(f"plugins {action}: ok (仅登记，不加载第三方代码)")
