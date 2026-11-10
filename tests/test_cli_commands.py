"""
Module: Test / CLI commands
Description: 旧库迁移、登录文件权限、模拟采集、比赛列表与插件登记命令。
Scope: Test
Notes: 只使用合成数据，不访问网络。
"""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from ojaudit import cli
from ojaudit.cli_operations import save_cookie
from ojaudit.core.analysis import run_analysis
from ojaudit.core.ingest import migrate_nowcoder
from ojaudit.core.schema import Contest, Participant, Submission
from ojaudit.core.store import Store
from ojaudit.tui.data import LocalContests
from ojaudit.tui.review_data import ReviewData


def test_legacy_sqlite_and_reviews_readonly(tmp_path):
    source = tmp_path / "nowcoder.db"
    code = "int main(){int value=1;return value+1;}"
    with sqlite3.connect(source) as conn:
        conn.executescript(
            "CREATE TABLE contests(contest_id INTEGER PRIMARY KEY,name TEXT);"
            "CREATE TABLE submissions(submission_id INTEGER PRIMARY KEY,contest_id INTEGER,"
            "student TEXT,student_id INTEGER,problem_index TEXT,language TEXT,"
            "phase TEXT,code TEXT,verdict TEXT,score REAL,submit_time INTEGER);"
        )
        conn.execute("INSERT INTO contests VALUES(123,'合成旧赛')")
        conn.execute("INSERT INTO contests VALUES(124,'合成旧赛二')")
        rows = [
            (1, 123, "虚构甲", 11, "A", 1000),
            (2, 123, "虚构乙", 22, "A", 2000),
            (3, 124, "虚构甲", 11, "B", 3000),
            (4, 124, "虚构丙", 33, "B", 4000),
            (5, 123, "虚构甲", 11, "B", 5000),
            (6, 123, "虚构丙", 33, "B", 6000),
        ]
        for sid, cid, name, uid, problem, when in rows:
            conn.execute(
                "INSERT INTO submissions VALUES(?,?,?,?,?,'C++','contest',?,'AC',100,?)",
                (sid, cid, name, uid, problem, code, when),
            )

    def review(uid_a, uid_b, problem, note):
        return {
            "run_id": "old-run",
            "uid_a": uid_a,
            "uid_b": uid_b,
            "problem_index": problem,
            "language": "C++",
            "status": "已核查",
            "note": note,
            "updated_at": "2026-01-01",
        }

    reviews = tmp_path / "reviews.json"
    reviews.write_text(
        json.dumps(
            [
                review("11", "22", 0, "旧记录"),
                review("11", "33", 1, "两场比赛都符合"),
                review("11", "99", 0, "找不到"),
            ]
        ),
        encoding="utf-8",
    )
    target = tmp_path / "new.db"
    with Store(target) as store:
        report = migrate_nowcoder(store, source, reviews)
        assert (report.submissions, report.reviews) == (6, 1)
        assert [item[-1] for item in report.skipped_reviews] == [
            "多场比赛都符合",
            "旧库中找不到双方的对应提交",
        ]
        assert store.list_contest_reviews("nowcoder", "123")[0]["note"] == "旧记录"
        assert migrate_nowcoder(store, source, reviews).submissions == 6
        assert store.execute("SELECT count(*) FROM submissions").fetchone()[0] == 6

        # 导入的复核在界面中可见；重新分析得到同一线索后状态沿用。
        local = LocalContests(target)
        data = ReviewData(local, Contest("nowcoder", "123", "合成旧赛"))
        history = [row for row in data.findings() if row["uid_b"] == "22"]
        assert history and history[0]["is_stale"] and history[0]["note"] == "旧记录"
        run_analysis(store, "nowcoder", "123", settings={})
        current = next(row for row in data.findings() if row["uid_b"] == "22")
        assert not current["is_stale"]
        assert current["status"] == "已核查"
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT count(*) FROM submissions").fetchone()[0] == 6


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


def _plugin_repo(tmp_path, manifest):
    """本地 git 仓库：真实 clone/checkout，不联网。"""
    import subprocess

    repo = tmp_path / "plugin-repo"
    (repo / "demo").mkdir(parents=True)
    (repo / "demo" / "plugin.toml").write_text(manifest, encoding="utf-8")
    # 仓库里放一个会留下痕迹的脚本与 hook，验证安装不会执行它们。
    (repo / "setup.py").write_text("open('EXECUTED', 'w').write('x')\n", encoding="utf-8")

    def git(*argv):
        return subprocess.run(
            ["git", "-C", str(repo), *argv], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "init")
    return repo, git("rev-parse", "HEAD")


GOOD_MANIFEST = (
    'name = "demo"\nkind = "exporter"\nversion = "1.0.0"\n'
    'api_version = 1\ndescription = "Synthetic plugin"\n'
)


def test_plugins_install_real_git_and_toggle(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    repo, sha = _plugin_repo(tmp_path, GOOD_MANIFEST)
    cli.main(["plugins", "install", f"file://{repo}@{sha[:10]}"])
    cli.main(["plugins", "enable", "demo"])
    cli.main(["plugins", "list"])
    out = capsys.readouterr().out
    assert "demo\t1.0.0\tenabled" in out and sha in out
    cli.main(["plugins", "disable", "demo"])
    registry_path = tmp_path / "config/ojaudit/plugins.json"
    registry = json.loads(registry_path.read_text())
    assert registry["demo"]["enabled"] is False
    assert registry_path.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "EXECUTED").exists()

    # 各种失败都不改动已有登记。
    before = registry_path.read_bytes()
    for spec in (
        f"file://{repo}@{'0' * 40}",
        f"ext::sh -c touch% EXECUTED@{sha}",
        f"file://{repo}@main",
        f"file://{tmp_path / 'missing'}@{sha}",
    ):
        with pytest.raises(SystemExit):
            cli.main(["plugins", "install", spec])
        assert registry_path.read_bytes() == before
    assert not (tmp_path / "EXECUTED").exists()


def test_plugins_install_rejects_invalid_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    repo, sha = _plugin_repo(tmp_path, 'name = "Bad Name"\n')
    with pytest.raises(SystemExit):
        cli.main(["plugins", "install", f"file://{repo}@{sha}"])
    assert not (tmp_path / "config/ojaudit/plugins.json").exists()


def test_registry_origin_has_no_credentials():
    from ojaudit.cli_operations import _redact

    assert _redact("https://user:token@example.invalid/x.git") == "https://example.invalid/x.git"
    assert _redact("git@example.invalid:x.git") == "git@example.invalid:x.git"
