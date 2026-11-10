"""
Module: CLI
Description: 本地比赛导入、筛选、检测、人工复核、排行榜导出和旧 JSON 迁移。
Scope: CLI
Notes: 默认离线；只处理显式指定的数据库与文件，不接触 TUI。
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ojaudit.cli_operations import (
    import_bundle,
    migrate_nowcoder,
    nowcoder_source,
    plugins_command,
    save_cookie,
)
from ojaudit.core.config import data_dir, load_config
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
    problem_titles = {}
    for item in submissions:
        index = int(item["problem_index"])
        title = str(item.get("problem_title") or "").strip()
        problem_titles.setdefault(index, title or f"题 {index}")
        if title:
            problem_titles[index] = title
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
        for index, title in sorted(problem_titles.items()):
            store.execute(
                """INSERT INTO problems(platform,contest_id,problem_index,problem_id,title,full_score)
                   VALUES (?,?,?,?,?,NULL)
                   ON CONFLICT(platform,contest_id,problem_index) DO UPDATE SET
                   title=CASE WHEN problems.title='' OR problems.title=('题 ' || problems.problem_index)
                              THEN excluded.title ELSE problems.title END""",
                (platform, cid, index, str(index), title),
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


def _analyze(
    store: Store, platform: str, cid: str, threshold: float, json_out: Path | None = None
) -> str:
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
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(
                {"run_id": run_id, "platform": platform, "contest_id": cid, "findings": findings},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(f"run_id={run_id} findings={len(findings)}")
    return run_id


def _rank_rows(store: Store, platform: str, cid: str) -> list[dict]:
    """复用 TUI 的同一份本地推导算法，保证 CLI 与 TUI 榜单一致。"""
    from ojaudit.tui.data import LocalContests
    from ojaudit.tui.ranking_data import derived_rows
    from ojaudit.tui.review_data import ReviewData

    return derived_rows(ReviewData(LocalContests(store.path), Contest(platform, cid, cid)))


def _export(store: Store, args: argparse.Namespace) -> Path:
    marks = {
        row["uid"]: row["mark"] for row in store.list_person_marks(args.platform, args.contest)
    }
    hidden = [HiddenPerson(**p) for p in store.list_hidden_people()]
    options = RankingOptions(cheaters=args.cheaters, suspects=args.suspects, managers=args.managers)
    ranking = build_final_ranking(
        _rank_rows(store, args.platform, args.contest), marks, hidden, options
    )
    from ojaudit.plugins.exporters.csv import export_csv
    from ojaudit.plugins.exporters.html import export_html
    from ojaudit.plugins.exporters.markdown import export_markdown

    fmt = getattr(args, "format", "csv")
    path = Path(args.output) if args.output else Path(f"{args.contest}.{fmt}")
    rows = list(ranking.rows)
    if fmt == "csv":
        export_csv(rows, path)
    elif fmt == "md":
        export_markdown(rows, path)
    else:
        export_html(rows, path)
    print(f"exported={path} rows={len(ranking.rows)}")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ojaudit", description="训练赛代码审查 CLI")
    parser.add_argument("--db", type=Path, default=None)
    sub = parser.add_subparsers(dest="command")

    migration = sub.add_parser("migrate", help="导入旧版 JSON 数据包")
    migration.add_argument("input", type=Path, nargs="?")
    migration.add_argument("--from-nowcoder-collect", action="store_true")
    migration.add_argument("--reviews", type=Path)
    migration.add_argument("--db", dest="legacy_db", type=Path)
    contests = sub.add_parser("contests", help="列出本地比赛并应用筛选")
    contests.add_argument("--all", action="store_true")
    analysis = sub.add_parser("analyze", help="分析本地已导入的比赛")
    analysis.add_argument("contest")
    analysis.add_argument("legacy_contest", nargs="?")
    analysis.add_argument("--platform", default="nowcoder")
    analysis.add_argument("--json-out", type=Path)
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

    export = sub.add_parser("export", help="导出本地最终排行榜（旧命令）")
    export.add_argument("platform")
    export.add_argument("contest")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--format", choices=["md", "csv", "html"], default="csv")
    rank = sub.add_parser("rank", help="生成最终排名")
    rank.add_argument("contest")
    rank.add_argument("--platform", default="nowcoder")
    rank.add_argument("--output", type=Path)
    rank.add_argument("--format", choices=["md", "csv", "html"], default="md")
    export.add_argument("--cheaters", choices=["drop", "mark"], default="drop")
    export.add_argument("--suspects", choices=["keep", "mark", "drop"], default="keep")
    export.add_argument("--managers", choices=["drop", "mark"], default="drop")
    rank.add_argument("--cheaters", choices=["drop", "mark"], default="drop")
    rank.add_argument("--suspects", choices=["keep", "mark", "drop"], default="keep")
    rank.add_argument("--managers", choices=["drop", "mark"], default="drop")
    plugins = sub.add_parser("plugins", help="插件登记")
    plugins.add_argument("action", choices=["list", "install", "enable", "disable"])
    plugins.add_argument("spec", nargs="?")
    login = sub.add_parser("login", help="保存牛客 Cookie 到权限 600 的本地文件")
    login.add_argument("--platform", choices=["nowcoder"], default="nowcoder")
    collect = sub.add_parser("collect", help="使用牛客 Source 只读采集")
    collect.add_argument("contest")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command is None:
        from importlib import import_module

        try:
            entry = import_module("ojaudit.tui.app").main
        except (ImportError, AttributeError) as exc:
            raise SystemExit("TUI 入口尚未就绪，请使用 ojaudit --help") from exc
        entry(db_path=args.db)
        return
    if args.command == "login":
        import getpass

        save_cookie(getpass.getpass("Nowcoder Cookie: "))
        print("Cookie 已保存至本地配置目录")
        return
    if args.command == "plugins":
        plugins_command(args.action, args.spec)
        return
    configured = load_config().get("storage", {})
    configured_db = configured.get("sqlite_path") if isinstance(configured, dict) else None
    db_path = args.db or (
        Path(configured_db).expanduser() if configured_db else data_dir() / "ojaudit.sqlite"
    )
    with Store(db_path) as store:
        if args.command == "migrate":
            if args.from_nowcoder_collect:
                if args.input:
                    raise ValueError("旧 SQLite 模式不接受 JSON 输入文件")
                source = args.legacy_db or Path("~/.dsh/nowcoder/nowcoder.db")
                count = migrate_nowcoder(store, source, args.reviews)
                print(f"migrated={count}")
            else:
                if args.input is None or args.reviews or args.legacy_db:
                    raise ValueError("JSON 模式需要输入文件；--reviews/--db 仅供旧库模式使用")
                platform, cid = _import_json(store, args.input)
                print(f"imported={platform}/{cid}")
        elif args.command == "contests":
            rows = store.execute(
                "SELECT platform, contest_id, name FROM contests ORDER BY platform, contest_id"
            ).fetchall()
            contests = [Contest(**dict(row)) for row in rows]
            for decision in filter_contests(contests, load_contest_filter()):
                if args.all or decision.visible:
                    print(
                        f"{decision.contest.platform}/{decision.contest.contest_id}\t"
                        f"{decision.contest.name}"
                    )
        elif args.command == "analyze":
            platform = args.contest if args.legacy_contest else args.platform
            cid = args.legacy_contest or args.contest
            _analyze(store, platform, cid, args.threshold, args.json_out)
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
        elif args.command in {"export", "rank"}:
            _export(store, args)
        elif args.command == "collect":
            bundle = nowcoder_source().fetch_contest(None, args.contest)
            import_bundle(store, bundle)
            print(f"collected={bundle.contest.contest_id} submissions={len(bundle.submissions)}")


if __name__ == "__main__":
    main()
