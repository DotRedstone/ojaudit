"""
Module: Deterministic Pipeline Tests
Description: 验证合成 SQLite 数据连续三次检测与导出逐字节一致。
Scope: Test
"""

from ojaudit.core.schema import Submission
from ojaudit.core.store import Store
from ojaudit.plugins.detectors.engine import analyze
from ojaudit.plugins.exporters.csv import export_csv
from ojaudit.plugins.exporters.html import export_html
from ojaudit.plugins.exporters.markdown import export_markdown


def _database(path):
    if not path.exists():
        store = Store(path)
        store.put_contest("synthetic", "demo", "Synthetic Contest")
        with store.connection:
            store.connection.executemany(
                "INSERT INTO participants(platform, contest_id, uid, name) VALUES (?, ?, ?, ?)",
                [
                    ("synthetic", "demo", "u1", "Synthetic A"),
                    ("synthetic", "demo", "u2", "Synthetic B"),
                ],
            )
            store.connection.executemany(
                """INSERT INTO submissions(
                    platform, contest_id, submission_id, uid, problem_index, language,
                    verdict, score, submit_time, phase, code, raw_meta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        "synthetic",
                        "demo",
                        "s1",
                        "u1",
                        0,
                        "cpp",
                        "Accepted",
                        100,
                        1000,
                        "contest",
                        "int main(){return 0;}",
                        "{}",
                    ),
                    (
                        "synthetic",
                        "demo",
                        "s2",
                        "u2",
                        0,
                        "cpp",
                        "Accepted",
                        100,
                        1200,
                        "contest",
                        "int main(){return 0;}",
                        "{}",
                    ),
                ],
            )
        store.close()
    store = Store(path)
    rows = store.execute(
        """SELECT * FROM submissions
           WHERE platform=? AND contest_id=? ORDER BY uid, submit_time, submission_id""",
        ("synthetic", "demo"),
    ).fetchall()
    submissions = [
        Submission(
            platform=row["platform"],
            contest_id=row["contest_id"],
            submission_id=row["submission_id"],
            uid=row["uid"],
            problem_index=row["problem_index"],
            language=row["language"],
            verdict=row["verdict"],
            score=row["score"],
            submit_time=row["submit_time"],
            phase=row["phase"],
            code=row["code"],
        )
        for row in rows
    ]
    return store, submissions


def _run_once(db_path, output_dir):
    store, submissions = _database(db_path)
    try:
        results = analyze(submissions)
        by_uid = {item.uid: item for item in submissions}
        report_rows = []
        for result in results:
            left, right = result["pair"]
            report_rows.append(
                {
                    **result,
                    "code_a": by_uid[left].code,
                    "code_b": by_uid[right].code,
                    "reason": result["verdict"],
                }
            )
        paths = [
            export_markdown(report_rows, output_dir / "report.md"),
            export_csv(report_rows, output_dir / "report.csv"),
            export_html(report_rows, output_dir / "report.html"),
        ]
        return tuple(path.read_bytes() for path in paths)
    finally:
        store.close()


def test_same_synthetic_database_three_runs_are_byte_identical(tmp_path):
    outputs = [
        _run_once(tmp_path / "source.sqlite", tmp_path / f"run-{index}") for index in range(3)
    ]
    assert outputs[0] == outputs[1] == outputs[2]
