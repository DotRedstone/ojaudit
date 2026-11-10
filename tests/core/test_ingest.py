"""
Module: Test / core ingest
Description: JSON 导入保存题目标题，题目表缺失时仍可按提交浏览题目。
Scope: Test
Notes: 只使用合成数据，不访问网络。
"""

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
