"""合成数据回归：迁移时保存题目，历史空题目库仍可按题浏览。"""

import json

from ojaudit.core.ingest import import_json
from ojaudit.core.schema import Contest
from ojaudit.core.store import Store
from ojaudit.tui.data import LocalContests
from ojaudit.tui.review_data import ReviewData


def test_json_migration_problems_and_legacy_fallback(tmp_path):
    db = tmp_path / "audit.sqlite"
    source = tmp_path / "bundle.json"
    source.write_text(
        json.dumps(
            {
                "contest": {"platform": "synthetic", "contest_id": "sample", "name": "sample"},
                "submissions": [
                    {
                        "submission_id": "s1",
                        "uid": "u1",
                        "problem_index": 0,
                        "problem_title": "加法",
                        "language": "cpp",
                        "code": "int main() {}",
                    },
                    {
                        "submission_id": "s2",
                        "uid": "u2",
                        "problem_index": 0,
                        "language": "cpp",
                        "code": "int main() { return 0; }",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with Store(db) as store:
        import_json(store, source)
        assert store.execute("SELECT count(*) FROM problems").fetchone()[0] == 1
    local = LocalContests(db)
    data = ReviewData(local, Contest("synthetic", "sample", "sample"))
    assert data.problems()[0]["title"] == "加法"
    assert len(data.submissions("u1", 0)) == 1
    assert local.stats(data.contest).problems == 1

    with Store(db) as store:
        store.execute("DELETE FROM problems")
        store.connection.commit()
    assert data.problems()[0]["title"] == "题 0"
    assert local.stats(data.contest).problems == 1
