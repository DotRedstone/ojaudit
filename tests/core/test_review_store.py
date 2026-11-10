"""
Module: Review Store Tests
Description: 验证全局隐藏人员、人员标记和线索复核分别持久化。
Scope: Test
"""

import pytest

from ojaudit.core.reviews import annotate_review_staleness, review_status
from ojaudit.core.store import Store


def test_hidden_people_and_manual_records_persist_independently(tmp_path):
    path = tmp_path / "review.sqlite"
    with Store(path) as store:
        store.put_hidden_person("synthetic", "manager", "管理员")
        store.put_person_mark("synthetic", "demo", "u1", "suspect", "备注", "2026-01-01T00:00:00Z")
        store.put_finding_review(
            "run-1",
            "u2",
            "u1",
            0,
            "cpp",
            "需进一步核实",
            "线索备注",
            "2026-01-02T00:00:00Z",
        )
    with Store(path) as store:
        assert store.list_hidden_people() == [
            {"platform": "synthetic", "uid": "manager", "nickname": "管理员"}
        ]
        assert store.list_person_marks("synthetic", "demo")[0]["mark"] == "suspect"
        reviews = store.list_finding_reviews("run-1")
        assert reviews[0]["uid_a"] == "u1"
        assert reviews[0]["uid_b"] == "u2"
        assert reviews[0]["status"] == "需进一步核实"
        stale = annotate_review_staleness(reviews, [])
        assert stale[0]["is_stale"] is True
        assert annotate_review_staleness(reviews, [reviews[0]])[0]["is_stale"] is False
        assert review_status(None) == "待复核"


def test_invalid_marks_and_review_statuses_are_rejected(tmp_path):
    with Store(tmp_path / "invalid.sqlite") as store:
        with pytest.raises(ValueError):
            store.put_person_mark("synthetic", "demo", "u1", "invalid", "", "now")
        with pytest.raises(ValueError):
            store.put_finding_review("run-1", "u1", "u2", 0, "cpp", "invalid", "", "now")
