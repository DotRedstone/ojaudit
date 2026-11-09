"""
Module: CLI
Description: 本地比赛导入、筛选、检测、人工复核、排行榜导出和旧 JSON 迁移。
Scope: CLI
Notes: 默认离线；只处理显式指定的数据库与文件，不接触 TUI。
"""

from __future__ import annotations

import argparse
import csv
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ojaudit.core.config import data_dir
from ojaudit.core.filters import filter_contests, load_contest_filter
from ojaudit.core.people import HiddenPerson, exclude_hidden_submissions
from ojaudit.core.ranking import RankingOptions, build_final_ranking
from ojaudit.core.schema import Contest, Submission, validate_submission
from ojaudit.core.store import Store
from ojaudit.plugins.detectors.classifier import classify
from ojaudit.plugins.detectors.pair import analyze_pair


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _import_json(store: Store, source: Path) -> tuple[str, str]:
    """导入合成/旧版 JSON 包；先验证结构，再写入标准 schema。"""
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("导入文件根节点必须是 JSON 对象")
    info = raw.get("contest", raw)
    platform = str(info.get("platform", raw.get("platform", "synthetic")))
    cid = str(info.get("contest_id", raw.get("contest_id", "")))
    name = str(info.get("name", raw.get("name", "")))
    if not all((platform, cid, name)):
        raise ValueError("导入包缺少比赛平台、ID 或名称")
    people = raw.get("participants", [])
    submissions = raw.get("submissions", [])
    if not isinstance(people, list) or not isinstance(submissions, list):
        raise TypeError("participants 和 submissions 必须是数组")
    parsed = []
    for item in submissions:
        row = Submission(
            platform,
            cid,
            str(item["submission_id"]),
            str(item["uid"]),
            int(item["problem_index"]),
            str(item["language"]),
            str(item.get("verdict", "")),
            float(item.get("score", 0)),
            int(item.get("submit_time", 0)),
            str(item.get("phase", "contest")),
            str(item.get("code", "")),
        )
        validate_submission(row)
        parsed.append(row)
    names = {str(p["uid"]): str(p.get("name", p["uid"])) for p in people}
    for row in parsed:
        names.setdefault(row.uid, row.uid)
    with store.connection:
        store.put_contest(platform, cid, name)
        for uid, person_name in sorted(names.items()):
            store.execute(
                """INSERT INTO participants(platform, contest_id, uid, name)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(platform, contest_id, uid) DO UPDATE SET name=excluded.name""",
                (platform, cid, uid, person_name),
            )
        for row in parsed:
            store.execute(
                """INSERT INTO submissions(
                       platform, contest_id, submission_id, uid, problem_index,
                       language, verdict, score, submit_time, phase, code
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(platform, contest_id, submission_id) DO UPDATE SET
                   uid=excluded.uid, problem_index=excluded.problem_index,
                   language=excluded.language, verdict=excluded.verdict,
                   score=excluded.score, submit_time=excluded.submit_time,
                   phase=excluded.phase, code=excluded.code""",
                (
                    row.platform,
                    row.contest_id,
                    row.submission_id,
                    row.uid,
                    row.problem_index,
                    row.language,
                    row.verdict,
                    row.score,
                    row.submit_time,
                    row.phase,
                    row.code,
                ),
            )
    return platform, cid


def _submissions(store: Store, platform: str, cid: str) -> list[Submission]:
    rows = store.execute(
        """SELECT * FROM submissions WHERE platform=? AND contest_id=?
           ORDER BY submission_id""",
        (platform, cid),
    ).fetchall()
    return [
        Submission(
            r["platform"],
            r["contest_id"],
            r["submission_id"],
            r["uid"],
            r["problem_index"],
            r["language"],
            r["verdict"],
            r["score"],
            r["submit_time"],
            r["phase"],
            r["code"],
        )
        for r in rows
    ]


def _analyze(store: Store, platform: str, cid: str, threshold: float) -> str:
    submissions = _submissions(store, platform, cid)
    hidden = tuple(HiddenPerson(**p) for p in store.list_hidden_people())
    visible = exclude_hidden_submissions(submissions, hidden)
    findings = classify(analyze_pair(visible, {"threshold": threshold}))
    run_id = uuid.uuid4().hex
    with store.connection:
        store.execute(
            """INSERT INTO analysis_runs(
                   run_id, platform, contest_id, plugin_set, created_from, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, platform, cid, "builtin-pair+classifier", "cli", _stamp()),
        )
        for item in findings:
            left, right = sorted(item["pair"])
            store.execute(
                """INSERT INTO findings(
                       run_id, uid_a, uid_b, problem_index, language,
                       verdict_level, scores, reasons
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    left,
                    right,
                    item["problem"],
                    item["language"],
                    item["level"],
                    json.dumps({"similarity": item["similarity"]}),
                    json.dumps(
                        [item["reason"], item["classification_reason"]],
                        ensure_ascii=False,
                    ),
                ),
            )
    print(f"run_id={run_id} findings={len(findings)}")
    return run_id


def _rank_rows(store: Store, platform: str, cid: str) -> list[dict]:
    rows = store.execute(
        """SELECT p.platform, p.uid, p.name, COALESCE(MAX(s.score), 0) AS score
           FROM participants p LEFT JOIN submissions s
             ON s.platform=p.platform AND s.contest_id=p.contest_id AND s.uid=p.uid
           WHERE p.platform=? AND p.contest_id=?
           GROUP BY p.platform, p.uid, p.name
           ORDER BY score DESC, p.uid""",
        (platform, cid),
    ).fetchall()
    return [{**dict(row), "rank": i} for i, row in enumerate(rows, 1)]


def _export(store: Store, args: argparse.Namespace) -> Path:
    marks = {
        row["uid"]: row["mark"] for row in store.list_person_marks(args.platform, args.contest)
    }
    hidden = [HiddenPerson(**p) for p in store.list_hidden_people()]
    options = RankingOptions(cheaters=args.cheaters, suspects=args.suspects, managers=args.managers)
    ranking = build_final_ranking(
        _rank_rows(store, args.platform, args.contest), marks, hidden, options
    )
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["rank", "uid", "name", "score", "person_mark"],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in ranking.rows:
            safe = dict(row)
            for key in ("uid", "name", "person_mark"):
                value = str(safe.get(key, ""))
                if value.startswith(("=", "+", "-", "@", "\t", "\r")):
                    safe[key] = "'" + value
            writer.writerow({key: safe.get(key, "") for key in writer.fieldnames})
    print(f"exported={path} rows={len(ranking.rows)}")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ojaudit", description="训练赛代码审查 CLI")
    parser.add_argument("--db", type=Path, default=data_dir() / "ojaudit.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)

    migration = sub.add_parser("migrate", help="导入旧版 JSON 数据包")
    migration.add_argument("input", type=Path)
    sub.add_parser("contests", help="列出本地比赛并应用筛选")
    analysis = sub.add_parser("analyze", help="分析本地已导入的比赛")
    analysis.add_argument("platform")
    analysis.add_argument("contest")
    analysis.add_argument("--threshold", type=float, default=0.5)

    mark = sub.add_parser("mark", help="人工标记比赛选手")
    mark.add_argument("platform")
    mark.add_argument("contest")
    mark.add_argument("uid")
    mark.add_argument("mark", choices=["normal", "suspect", "cheater"])
    mark.add_argument("--note", default="")

    review = sub.add_parser("review", help="复核一条检测线索")
    review.add_argument("run_id")
    review.add_argument("uid_a")
    review.add_argument("uid_b")
    review.add_argument("problem_index", type=int)
    review.add_argument("language")
    review.add_argument("status", choices=["已核查", "无需跟进", "需进一步核实"])
    review.add_argument("--note", default="")

    people = sub.add_parser("hidden", help="全局管理者名单")
    people.add_argument("action", choices=["add", "remove", "list"])
    people.add_argument("--platform")
    people.add_argument("--uid")
    people.add_argument("--nickname", default="")

    export = sub.add_parser("export", help="导出本地最终排行榜 CSV")
    export.add_argument("platform")
    export.add_argument("contest")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--cheaters", choices=["drop", "mark"], default="drop")
    export.add_argument("--suspects", choices=["keep", "mark", "drop"], default="keep")
    export.add_argument("--managers", choices=["drop", "mark"], default="drop")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    with Store(args.db) as store:
        if args.command == "migrate":
            platform, cid = _import_json(store, args.input)
            print(f"imported={platform}/{cid}")
        elif args.command == "contests":
            rows = store.execute(
                "SELECT platform, contest_id, name FROM contests ORDER BY platform, contest_id"
            ).fetchall()
            contests = [Contest(**dict(row)) for row in rows]
            for decision in filter_contests(contests, load_contest_filter()):
                if decision.visible:
                    print(
                        f"{decision.contest.platform}/{decision.contest.contest_id}\t"
                        f"{decision.contest.name}"
                    )
        elif args.command == "analyze":
            _analyze(store, args.platform, args.contest, args.threshold)
        elif args.command == "mark":
            store.put_person_mark(
                args.platform, args.contest, args.uid, args.mark, args.note, _stamp()
            )
            print("marked")
        elif args.command == "review":
            store.put_finding_review(
                args.run_id,
                args.uid_a,
                args.uid_b,
                args.problem_index,
                args.language,
                args.status,
                args.note,
                _stamp(),
            )
            print("reviewed")
        elif args.command == "hidden":
            if args.action == "list":
                for person in store.list_hidden_people():
                    print(f"{person['platform']}/{person['uid']}\t{person['nickname']}")
            else:
                if not args.platform or not args.uid:
                    raise ValueError("hidden add/remove 必须提供 --platform 和 --uid")
                if args.action == "add":
                    store.put_hidden_person(args.platform, args.uid, args.nickname)
                else:
                    store.remove_hidden_person(args.platform, args.uid)
                print("updated")
        elif args.command == "export":
            _export(store, args)


if __name__ == "__main__":
    main()
