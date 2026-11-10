"""
Module: CLI R10 Tests
Description: 合成旧库迁移、插件注册、采集 mock 与多格式导出。
Scope: Test
"""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from ojaudit import cli
from ojaudit.cli_operations import save_cookie
from ojaudit.core.ingest import migrate_nowcoder
from ojaudit.core.schema import Contest, Participant, Submission
from ojaudit.core.store import Store


def test_legacy_sqlite_and_reviews_readonly(tmp_path):
    source = tmp_path / "nowcoder.db"
    with sqlite3.connect(source) as conn:
        conn.executescript(
            "CREATE TABLE contests(contest_id INTEGER PRIMARY KEY,name TEXT);"
            "CREATE TABLE submissions(submission_id INTEGER PRIMARY KEY,contest_id INTEGER,"
            "student TEXT,student_id INTEGER,problem_index TEXT,language TEXT,"
            "phase TEXT,code TEXT,verdict TEXT,score REAL,submit_time INTEGER);"
        )
        conn.execute("INSERT INTO contests VALUES(123,'合成旧赛')")
        conn.execute(
            "INSERT INTO submissions VALUES(1,123,'虚构甲',11,'A','C++','contest',"
            "'int main(){}','AC',100,1)"
        )
    reviews = tmp_path / "reviews.json"
    reviews.write_text(
        json.dumps(
            [
                {
                    "run_id": "old-run",
                    "uid_a": "11",
                    "uid_b": "22",
                    "problem_index": 0,
                    "language": "cpp",
                    "status": "已核查",
                    "note": "旧记录",
                    "updated_at": "2026-01-01",
                }
            ]
        ),
        encoding="utf-8",
    )
    target = tmp_path / "new.db"
    with Store(target) as store:
        assert migrate_nowcoder(store, source, reviews) == 1
        assert store.execute("SELECT uid FROM submissions").fetchone()[0] == "11"
        assert store.list_finding_reviews("old-run")[0]["note"] == "旧记录"
        assert migrate_nowcoder(store, source, reviews) == 1
        assert store.execute("SELECT count(*) FROM submissions").fetchone()[0] == 1
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT count(*) FROM submissions").fetchone()[0] == 1


def test_login_file_mode_and_mock_collect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr("getpass.getpass", lambda _: "session=synthetic")
    db = tmp_path / "local.db"
    cli.main(["--db", str(db), "login"])
    cookie = tmp_path / "config/ojaudit/nowcoder.cookie"
    assert cookie.read_text() == "session=synthetic"
    assert cookie.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        save_cookie("bad\ncookie")
    bundle = SimpleNamespace(
        contest=Contest("nowcoder", "123", "合成赛"),
        participants=(Participant("nowcoder", "123", "11", "虚构甲"),),
        problems=(),
        submissions=(
            Submission(
                "nowcoder", "123", "1", "11", 0, "cpp", "AC", 100, 1, "contest", "int main(){}"
            ),
        ),
    )
    monkeypatch.setattr(
        cli,
        "nowcoder_source",
        lambda: SimpleNamespace(fetch_contest=lambda session, cid: bundle),
    )
    cli.main(["--db", str(db), "collect", "123"])
    output = tmp_path / "report.json"
    cli.main(["--db", str(db), "analyze", "123", "--json-out", str(output)])
    assert json.loads(output.read_text())["contest_id"] == "123"
    for fmt in ("md", "csv", "html"):
        path = tmp_path / f"rank.{fmt}"
        cli.main(["--db", str(db), "rank", "123", "--format", fmt, "--output", str(path)])
        assert path.is_file() and path.stat().st_size > 0


def test_contests_all_and_plugins_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db = tmp_path / "db.sqlite"
    with Store(db) as store:
        store.put_contest("nowcoder", "1", "训练赛")
    cli.main(["--db", str(db), "contests", "--all"])
    assert "训练赛" in capsys.readouterr().out
    cli.main(["plugins", "list"])
    assert capsys.readouterr().out == ""


def test_plugins_install_and_toggle_without_loading_code(tmp_path, monkeypatch, capsys):
    from ojaudit import cli_operations

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    calls = []

    def fake_git(argv, **kwargs):
        calls.append(argv)
        if "clone" in argv:
            destination = argv[-1]
            root = __import__("pathlib").Path(destination)
            (root / "demo").mkdir(parents=True)
            (root / "demo" / "plugin.toml").write_text(
                'name = "demo"\nkind = "exporter"\nversion = "1.0.0"\n'
                'api_version = 1\ndescription = "Synthetic plugin"\n',
                encoding="utf-8",
            )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_operations.subprocess, "run", fake_git)
    cli.main(["plugins", "install", "https://example.invalid/demo.git@abcdef1234567"])
    cli.main(["plugins", "enable", "demo"])
    cli.main(["plugins", "list"])
    assert "demo" in capsys.readouterr().out
    cli.main(["plugins", "disable", "demo"])
    assert len(calls) == 2
    registry = json.loads((tmp_path / "config/ojaudit/plugins.json").read_text())
    assert registry["demo"]["enabled"] is False
