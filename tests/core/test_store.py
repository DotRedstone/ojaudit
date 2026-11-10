"""
Module: Store Tests
Description: 验证 SQLite 初始化、迁移和比赛写入。
Scope: Test
"""

from ojaudit.core.store import Store


def test_store_migrates_and_persists_contest(tmp_path):
    path = tmp_path / "db" / "test.sqlite"
    with Store(path) as store:
        store.put_contest("demo", "c1", "合成训练赛")
        row = store.execute(
            "SELECT name FROM contests WHERE platform=? AND contest_id=?",
            ("demo", "c1"),
        ).fetchone()
        assert row["name"] == "合成训练赛"
        assert store.execute("SELECT version FROM schema_version").fetchone()[0] == 1
