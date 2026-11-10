"""
Module: TUI / editable settings lists
Description: 暂存逐条比赛筛选规则及管理者名单修改，不影响现有导航键位。
Scope: TUI
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ojaudit.core.store import Store


class EditableLists:
    def __init__(self, config: dict[str, Any], db_path: Path, platform: str) -> None:
        filt = config.get("contest_filter", {})
        filt = filt if isinstance(filt, dict) else {}
        self.rules: dict[str, list[dict[str, Any]]] = {
            group: [dict(row) for row in filt.get(group, [])]
            for group in ("whitelist", "blacklist")
        }
        people = config.get("people", {})
        people = people if isinstance(people, dict) else {}
        raw = people.get("manager_entries", [])
        managers = {
            str(row["uid"]): {
                "uid": str(row["uid"]),
                "nickname": str(row.get("nickname", "")),
                "enabled": bool(row.get("enabled", True)),
            }
            for row in raw
            if isinstance(row, dict) and isinstance(row.get("uid"), str)
        }
        if db_path.is_file():
            with Store(db_path) as store:
                for row in store.list_hidden_people():
                    if row["platform"] == platform:
                        managers[row["uid"]] = {
                            "uid": row["uid"],
                            "nickname": row["nickname"],
                            "enabled": True,
                        }
        self.managers = list(managers.values())
        self.baseline = self.signature()

    def signature(self) -> tuple:
        return (
            tuple(
                tuple(
                    (row.get("pattern", ""), row.get("enabled", True)) for row in self.rules[group]
                )
                for group in ("whitelist", "blacklist")
            ),
            tuple((row["uid"], row["nickname"], row["enabled"]) for row in self.managers),
        )

    @property
    def dirty(self) -> bool:
        return self.signature() != self.baseline

    def options(self, option_factory: Any) -> list[Any]:
        result = []
        for group, name in (("whitelist", "白名单"), ("blacklist", "黑名单")):
            for index, _row in enumerate(self.rules[group]):
                prefix = f"contest_filter.{group}.{index}"
                result.append(
                    option_factory(
                        "比赛筛选", prefix + ".pattern", f"{name} {index + 1} · 正则", "text", ""
                    )
                )
                result.append(
                    option_factory(
                        "比赛筛选", prefix + ".enabled", f"{name} {index + 1} · 启用", "bool", True
                    )
                )
        for index, _row in enumerate(self.managers):
            prefix = f"people.manager_entries.{index}"
            result.append(
                option_factory("人员名单", prefix + ".uid", f"管理者 {index + 1} · UID", "text", "")
            )
            result.append(
                option_factory(
                    "人员名单", prefix + ".nickname", f"管理者 {index + 1} · 姓名", "text", ""
                )
            )
            result.append(
                option_factory(
                    "人员名单", prefix + ".enabled", f"管理者 {index + 1} · 启用", "bool", True
                )
            )
        return result

    def value(self, key: str) -> Any:
        parts = key.split(".")
        if parts[0] == "contest_filter" and len(parts) == 4:
            return self.rules[parts[1]][int(parts[2])][parts[3]]
        return self.managers[int(parts[2])][parts[3]]

    @staticmethod
    def is_list_key(key: str) -> bool:
        return key.startswith(
            (
                "contest_filter.whitelist.",
                "contest_filter.blacklist.",
                "people.manager_entries.",
            )
        )

    def change(self, key: str, value: Any) -> None:
        parts = key.split(".")
        if parts[0] == "contest_filter":
            self.rules[parts[1]][int(parts[2])][parts[3]] = value
        else:
            self.managers[int(parts[2])][parts[3]] = value

    def add(self, category: str, group: str = "whitelist") -> None:
        if category == "比赛筛选" and group in self.rules:
            self.rules[group].append({"pattern": "", "enabled": True})
        elif category == "人员名单":
            self.managers.append({"uid": "", "nickname": "", "enabled": True})
        else:
            raise ValueError("此分类没有可新增的列表")

    def remove(self, key: str) -> None:
        if not self.is_list_key(key):
            raise ValueError("只能删除列表条目")
        parts = key.split(".")
        if parts[0] == "contest_filter":
            self.rules[parts[1]].pop(int(parts[2]))
        else:
            self.managers.pop(int(parts[2]))

    def validate(self) -> None:
        for rows in self.rules.values():
            for item in rows:
                pattern = item.get("pattern")
                if not isinstance(pattern, str) or not pattern:
                    raise ValueError("规则正则不能为空；请填写或删除新规则")
                if not isinstance(item.get("enabled"), bool):
                    raise TypeError("规则启用标记必须为布尔值")
                re.compile(pattern)
        seen: set[str] = set()
        for row in self.managers:
            uid = row["uid"].strip()
            if not uid or uid in seen:
                raise ValueError("管理者 UID 不能为空或重复")
            seen.add(uid)
            if not isinstance(row["enabled"], bool):
                raise TypeError("管理者启用标记必须为布尔值")

    def write_config(self, config: dict[str, Any]) -> None:
        config.setdefault("contest_filter", {})
        for group in ("whitelist", "blacklist"):
            config["contest_filter"][group] = [dict(row) for row in self.rules[group]]
        config.setdefault("people", {})["manager_entries"] = [dict(row) for row in self.managers]

    def write_people(self, db_path: Path, platform: str) -> None:
        if not db_path.is_file():
            raise ValueError("本地数据库不存在，不能编辑管理者名单")
        incoming = {row["uid"]: row["nickname"] for row in self.managers if row["enabled"]}
        with Store(db_path) as store:
            existing = {
                row["uid"]: row["nickname"]
                for row in store.list_hidden_people()
                if row["platform"] == platform
            }
            for uid in existing.keys() - incoming.keys():
                store.remove_hidden_person(platform, uid)
            for uid, nickname in incoming.items():
                if existing.get(uid) != nickname:
                    store.put_hidden_person(platform, uid, nickname)
