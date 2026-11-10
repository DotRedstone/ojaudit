"""
Module: People And Ranking Tests
Description: 验证全局管理者隔离和三类人员的最终排名策略。
Scope: Test
"""

from ojaudit.core.people import (
    HiddenPerson,
    exclude_hidden_participants,
    exclude_hidden_submissions,
)
from ojaudit.core.ranking import RankingOptions, build_final_ranking
from ojaudit.core.schema import Participant, Submission


def submission(uid, platform="synthetic"):
    return Submission(
        platform,
        "demo",
        f"sub-{uid}",
        uid,
        0,
        "cpp",
        "Accepted",
        100,
        1000,
        "contest",
        "int main(){return 0;}",
    )


def test_hidden_people_are_removed_before_detection_pairing():
    hidden = [HiddenPerson("synthetic", "manager", "管理者")]
    participants = [
        Participant("synthetic", "demo", "manager", "管理者"),
        Participant("synthetic", "demo", "student", "选手"),
    ]
    submissions = [submission("manager"), submission("student")]
    assert [p.uid for p in exclude_hidden_participants(participants, hidden)] == ["student"]
    assert [s.uid for s in exclude_hidden_submissions(submissions, hidden)] == ["student"]
    assert len(exclude_hidden_submissions([submission("manager", "other")], hidden)) == 1


def test_cheater_drop_and_suspect_mark_resequence_remaining_rows():
    rows = [
        {"platform": "synthetic", "uid": "u1", "rank": 1},
        {"platform": "synthetic", "uid": "u2", "rank": 2},
        {"platform": "synthetic", "uid": "u3", "rank": 3},
    ]
    result = build_final_ranking(
        rows,
        {"u2": "cheater", "u3": "suspect"},
        options=RankingOptions(cheaters="drop", suspects="mark"),
    )
    assert [(r["uid"], r["rank"]) for r in result.rows] == [("u1", 1), ("u3", 2)]
    assert result.rows[1]["person_mark"] == "suspect"


def test_suspect_keep_mark_and_drop_modes():
    rows = [{"uid": "u1", "rank": 1}, {"uid": "u2", "rank": 2}]
    keep = build_final_ranking(rows, {"u2": "suspect"}, options=RankingOptions(suspects="keep"))
    mark = build_final_ranking(rows, {"u2": "suspect"}, options=RankingOptions(suspects="mark"))
    drop = build_final_ranking(rows, {"u2": "suspect"}, options=RankingOptions(suspects="drop"))
    assert len(keep.rows) == 2 and "person_mark" not in keep.rows[1]
    assert mark.rows[1]["person_mark"] == "suspect"
    assert [r["uid"] for r in drop.rows] == ["u1"]


def test_cheater_and_manager_mark_modes():
    rows = [
        {"platform": "synthetic", "uid": "u1", "rank": 1},
        {"platform": "synthetic", "uid": "manager", "rank": 2},
    ]
    hidden = [HiddenPerson("synthetic", "manager", "管理者")]
    result = build_final_ranking(
        rows,
        {"u1": "cheater"},
        hidden,
        RankingOptions(cheaters="mark", managers="mark"),
    )
    assert result.rows[0]["person_mark"] == "cheater"
    assert result.rows[1]["person_mark"] == "manager"
    assert [r["rank"] for r in result.rows] == [1, 2]


def test_derived_ranking_counts_only_contest_phase():
    from ojaudit.core.ranking import derive_rows

    rows = derive_rows(
        "demo",
        [("u1", "甲"), ("u2", "乙"), ("u3", "丙")],
        [
            ("u1", 0, 100, 10, "contest"),
            ("u1", 0, 60, 5, "contest"),
            ("u2", 0, 100, 20, "contest"),
            ("u2", 1, 100, 99, "after"),
            ("u3", 1, 100, 1, "before"),
        ],
    )
    assert [(row["uid"], row["score"], row["rank"]) for row in rows] == [
        ("u1", 100, 1),
        ("u2", 100, 2),
        ("u3", 0, 3),
    ]
