"""
Module: CLI
Description: 本地比赛导入、筛选、检测、人工复核、排行榜导出和旧 JSON 迁移。
Scope: CLI
Notes: 默认离线；只处理显式指定的数据库与文件，不接触 TUI。
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from ojaudit.cli_operations import nowcoder_source, plugins_command, save_cookie
from ojaudit.core.analysis import run_analysis
from ojaudit.core.config import data_dir, load_config
from ojaudit.core.filters import filter_contests, load_contest_filter
from ojaudit.core.ingest import import_bundle, import_json, migrate_nowcoder
from ojaudit.core.people import HiddenPerson
from ojaudit.core.ranking import RankingOptions, build_final_ranking
from ojaudit.core.schema import Contest
from ojaudit.core.store import Store


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _analyze(
    store: Store,
    platform: str,
    cid: str,
    threshold: float | None = None,
    json_out: Path | None = None,
) -> str:
    result = run_analysis(store, platform, cid, threshold=threshold, created_from="cli")
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "platform": platform,
                    "contest_id": cid,
                    "findings": list(result.findings),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(f"run_id={result.run_id} findings={len(result.findings)}")
    return result.run_id


def _rank_rows(store: Store, platform: str, cid: str) -> list[dict]:
    """复用 TUI 的同一份本地推导算法，保证 CLI 与 TUI 榜单一致。"""
    from ojaudit.tui.data import LocalContests
    from ojaudit.tui.ranking_data import derived_rows
    from ojaudit.tui.review_data import ReviewData

    return derived_rows(ReviewData(LocalContests(store.path), Contest(platform, cid, cid)))


def _export(store: Store, args: argparse.Namespace) -> Path:
    if not store.contest_exists(args.platform, args.contest):
        raise ValueError(f"比赛不存在：{args.platform}/{args.contest}；请先 collect 或 migrate")
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
    analysis.add_argument(
        "--threshold", type=float, default=None, help="指纹相似度阈值，默认取设置"
    )

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
                contest = import_json(store, args.input)
                print(f"imported={contest.platform}/{contest.contest_id}")
        elif args.command == "contests":
            for decision in filter_contests(store.list_contests(), load_contest_filter()):
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
            collect_settings = load_config().get("collect", {})
            collect_settings = collect_settings if isinstance(collect_settings, dict) else {}
            bundle = nowcoder_source().fetch_contest(None, args.contest)
            import_bundle(store, bundle)
            print(f"collected={bundle.contest.contest_id} submissions={len(bundle.submissions)}")
            if collect_settings.get("auto_analyze", False):
                _analyze(store, bundle.contest.platform, bundle.contest.contest_id)


if __name__ == "__main__":
    main()
