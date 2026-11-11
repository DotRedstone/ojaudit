"""
Module: Core / review exchange
Description: 人工复核结果的导出与合并导入：人员结论、线索复核与管理者名单，便于多人分头排查后汇总。
Scope: Core
Notes:
- 文件只含人工结论与选手名称、UID，不含代码、Cookie 或检测原始数据。
- 合并规则：作弊 > 存疑 > 正常，取更重的结论；备注合并并注明来源；不同的结论记为冲突供复查。
- 线索复核按（双方 UID、题号、语言）匹配，不依赖分析轮次；本地尚未分析的比赛，复核先存下，
  之后分析出同一条线索时自动生效。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ojaudit.core.reviews import finding_key

FORMAT = "ojaudit-reviews"
VERSION = 1
_MARK_RANK = {"normal": 1, "suspect": 2, "cheater": 3}
_STATUS_RANK = {"无需跟进": 1, "需进一步核实": 2, "已核查": 3}
MARK_NAMES = {"normal": "正常", "suspect": "存疑", "cheater": "作弊"}
STATUS_NAMES = {"无需跟进": "正常", "需进一步核实": "存疑", "已核查": "作弊"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def export_reviews(store: Any, contests: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """导出所选比赛（默认全部有人工结论的比赛）的人工结论。"""
    keys = contests
    if keys is None:
        rows = store.connection.execute(
            "SELECT DISTINCT platform, contest_id FROM person_marks UNION "
            "SELECT DISTINCT platform, contest_id FROM finding_reviews "
            "WHERE platform IS NOT NULL ORDER BY 1, 2"
        ).fetchall()
        keys = [(str(row[0]), str(row[1])) for row in rows]
    result = []
    for platform, contest_id in keys:
        row = store.connection.execute(
            "SELECT name, start_time FROM contests WHERE platform=? AND contest_id=?",
            (platform, contest_id),
        ).fetchone()
        names = dict(store.participants(platform, contest_id))
        people = [
            {
                "uid": mark["uid"],
                "name": names.get(mark["uid"], ""),
                "mark": mark["mark"],
                "note": mark["note"],
            }
            for mark in store.list_person_marks(platform, contest_id)
        ]
        latest: dict[tuple[str, str, int, str], dict[str, Any]] = {}
        for review in store.list_contest_reviews(platform, contest_id):
            latest.setdefault(finding_key(review), review)
        findings = [
            {
                "uid_a": key[0],
                "uid_b": key[1],
                "problem_index": key[2],
                "language": key[3],
                "status": review["status"],
                "note": review["note"],
            }
            for key, review in sorted(latest.items())
        ]
        if not people and not findings:
            continue
        result.append(
            {
                "platform": platform,
                "contest_id": contest_id,
                "name": str(row[0]) if row else contest_id,
                "start_time": row[1] if row else None,
                "people": people,
                "findings": findings,
            }
        )
    return {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": _now(),
        "contests": result,
        "managers": [dict(row) for row in store.list_hidden_people()],
    }


def write_reviews(data: dict[str, Any], destination: str | Path) -> Path:
    path = Path(destination).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_reviews(source: str | Path) -> dict[str, Any]:
    """读取并校验交换文件；格式不对时抛 ValueError。"""
    path = Path(source).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"无法读取：{exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"不是有效的 JSON：{exc.msg}") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("不是 ojaudit 复核结果文件")
    if data.get("version") != VERSION:
        raise ValueError(f"不支持的版本：{data.get('version')}")
    contests = data.get("contests")
    if not isinstance(contests, list):
        raise ValueError("contests 必须是列表")  # noqa: TRY004 - 文件格式错误统一按 ValueError 提示
    for contest in contests:
        if not isinstance(contest, dict) or not all(
            isinstance(contest.get(key), str) and contest.get(key)
            for key in ("platform", "contest_id")
        ):
            raise ValueError("比赛缺少 platform / contest_id")
        for person in contest.get("people", []):
            if person.get("mark") not in _MARK_RANK or not person.get("uid"):
                raise ValueError(f"人员结论无效：{person}")
        for item in contest.get("findings", []):
            if item.get("status") not in _STATUS_RANK or not item.get("uid_a"):
                raise ValueError(f"线索复核无效：{item}")
    return data


@dataclass
class ImportReport:
    contests: int = 0
    contests_added: int = 0
    marks_added: int = 0
    marks_raised: int = 0
    reviews_added: int = 0
    reviews_raised: int = 0
    managers_added: int = 0
    # 冲突：(比赛名, 对象, 本地结论, 导入结论, 采用的结论)
    conflicts: list[tuple[str, str, str, str, str]] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.contests} 场比赛"]
        if self.contests_added:
            parts.append(f"新登记 {self.contests_added} 场（未采集）")
        parts.append(f"人员结论新增 {self.marks_added}、加重 {self.marks_raised}")
        parts.append(f"线索复核新增 {self.reviews_added}、加重 {self.reviews_raised}")
        if self.managers_added:
            parts.append(f"管理者新增 {self.managers_added}")
        parts.append(f"冲突 {len(self.conflicts)} 处")
        return "，".join(parts)


def _merge_note(local: str, imported: str, source: str) -> str:
    if not imported or imported in local:
        return local
    tagged = f"{imported}（{source}）" if source else imported
    return f"{local}；{tagged}" if local else tagged


def import_reviews(store: Any, data: dict[str, Any], source: str = "") -> ImportReport:
    """合并导入：取更重的结论，备注合并，冲突记入报告。整个导入在一个事务中完成。"""
    report = ImportReport()
    now = _now()
    with store.transaction():
        for contest in data["contests"]:
            platform, contest_id = contest["platform"], contest["contest_id"]
            name = str(contest.get("name") or contest_id)
            report.contests += 1
            if not store.contest_exists(platform, contest_id):
                store.put_contest_listing(
                    platform, contest_id, name, contest.get("start_time"), None
                )
                report.contests_added += 1
            local_marks = {row["uid"]: row for row in store.list_person_marks(platform, contest_id)}
            for person in contest.get("people", []):
                uid, mark = str(person["uid"]), str(person["mark"])
                note = str(person.get("note", ""))
                who = f"{person.get('name') or uid}（{uid}）"
                current = local_marks.get(uid)
                if current is None:
                    store.put_person_mark(platform, contest_id, uid, mark, note, now)
                    report.marks_added += 1
                    continue
                stronger = _MARK_RANK[mark] > _MARK_RANK.get(current["mark"], 0)
                if mark != current["mark"]:
                    chosen = mark if stronger else current["mark"]
                    report.conflicts.append(
                        (name, who, MARK_NAMES[current["mark"]], MARK_NAMES[mark],
                         MARK_NAMES[chosen])
                    )  # fmt: skip
                merged = _merge_note(current["note"], note, source)
                if stronger or merged != current["note"]:
                    store.put_person_mark(
                        platform, contest_id, uid, mark if stronger else current["mark"],
                        merged, now,
                    )  # fmt: skip
                    report.marks_raised += int(stronger)
            run = store.connection.execute(
                "SELECT run_id FROM analysis_runs WHERE platform=? AND contest_id=? "
                "ORDER BY created_at DESC, run_id DESC LIMIT 1",
                (platform, contest_id),
            ).fetchone()
            run_id = str(run[0]) if run else f"imported:{platform}/{contest_id}"
            local_reviews: dict[tuple[str, str, int, str], dict[str, Any]] = {}
            for review in store.list_contest_reviews(platform, contest_id):
                local_reviews.setdefault(finding_key(review), review)
            for item in contest.get("findings", []):
                key = finding_key(item)
                status, note = str(item["status"]), str(item.get("note", ""))
                current = local_reviews.get(key)
                label = f"{key[0]} ↔ {key[1]} · 第 {key[2] + 1} 题"
                if current is None:
                    store.put_finding_review(
                        run_id, key[0], key[1], key[2], key[3], status, note, now,
                        platform=platform, contest_id=contest_id,
                    )  # fmt: skip
                    report.reviews_added += 1
                    continue
                stronger = _STATUS_RANK[status] > _STATUS_RANK.get(current["status"], 0)
                if status != current["status"]:
                    chosen = status if stronger else current["status"]
                    report.conflicts.append(
                        (name, label, STATUS_NAMES.get(current["status"], current["status"]),
                         STATUS_NAMES[status], STATUS_NAMES.get(chosen, chosen))
                    )  # fmt: skip
                merged = _merge_note(current["note"], note, source)
                if stronger or merged != current["note"]:
                    store.put_finding_review(
                        current["run_id"], key[0], key[1], key[2], key[3],
                        status if stronger else current["status"], merged, now,
                        platform=platform, contest_id=contest_id,
                    )  # fmt: skip
                    report.reviews_raised += int(stronger)
        existing = {(row["platform"], row["uid"]) for row in store.list_hidden_people()}
        for manager in data.get("managers", []):
            key = (str(manager.get("platform", "")), str(manager.get("uid", "")))
            if all(key) and key not in existing:
                store.put_hidden_person(*key, str(manager.get("nickname", "")))
                existing.add(key)
                report.managers_added += 1
    return report
