"""
Module: Core / filters
Description: 比赛过滤规则：一组正则，配合「黑名单 / 白名单」模式决定比赛是否显示。
Scope: Core
Notes:
- 默认黑名单模式且无规则，即显示全部比赛。
- 黑名单：命中任一启用规则的比赛被隐藏；白名单：只显示命中任一启用规则的比赛，
  没有启用的规则时显示全部。
- 兼容旧配置 whitelist / blacklist 两组列表：有启用的白名单规则时按白名单读取。
- excluded 为手动剔除的比赛（「平台/比赛 ID」），不论模式与规则一律隐藏，不必写正则。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from ojaudit.core.schema import Contest

Mode = Literal["blacklist", "whitelist"]


@dataclass(frozen=True, slots=True)
class ContestRule:
    pattern: str
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ContestFilter:
    rules: tuple[ContestRule, ...] = ()
    mode: Mode = "blacklist"
    match_field: Literal["name", "name_id"] = "name"
    case_sensitive: bool = False
    excluded: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(key, str) for key in self.excluded):
            raise TypeError("excluded 必须为「平台/比赛 ID」字符串列表")
        if self.mode not in {"blacklist", "whitelist"}:
            raise ValueError("过滤模式必须为 blacklist 或 whitelist")
        if self.match_field not in {"name", "name_id"}:
            raise ValueError("比赛匹配字段必须为 name 或 name_id")
        if not isinstance(self.case_sensitive, bool):
            raise TypeError("case_sensitive 必须为布尔值")
        for rule in self.rules:
            if not isinstance(rule.pattern, str) or not isinstance(rule.enabled, bool):
                raise TypeError("比赛规则 pattern/enabled 字段类型无效")
            check_pattern(rule.pattern, self.case_sensitive)

    @property
    def active(self) -> tuple[ContestRule, ...]:
        return tuple(rule for rule in self.rules if rule.enabled and rule.pattern)


def check_pattern(pattern: str, case_sensitive: bool = False) -> None:
    try:
        re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"正则无效：{exc}") from exc


@dataclass(frozen=True, slots=True)
class ContestDecision:
    contest: Contest
    visible: bool
    reason: str


_DEFAULT_FILTER = ContestFilter()


def matches(contest: Contest, rule: ContestRule, config: ContestFilter = _DEFAULT_FILTER) -> bool:
    candidate = contest.name
    if config.match_field == "name_id":
        candidate += " " + contest.contest_id
    flags = 0 if config.case_sensitive else re.IGNORECASE
    return bool(rule.pattern) and bool(re.search(rule.pattern, candidate, flags))


def contest_key(contest: Contest) -> str:
    return f"{contest.platform}/{contest.contest_id}"


def evaluate_contest(contest: Contest, config: ContestFilter = _DEFAULT_FILTER) -> ContestDecision:
    if contest_key(contest) in config.excluded:
        return ContestDecision(contest, False, "已手动剔除")
    rules = config.active
    hit = next((rule for rule in rules if matches(contest, rule, config)), None)
    if config.mode == "blacklist":
        if hit is not None:
            return ContestDecision(contest, False, f"命中黑名单 {hit.pattern}")
        return ContestDecision(contest, True, "未命中黑名单")
    if not rules:
        return ContestDecision(contest, True, "白名单为空")
    if hit is not None:
        return ContestDecision(contest, True, f"命中白名单 {hit.pattern}")
    return ContestDecision(contest, False, "未命中白名单")


def filter_contests(
    contests: list[Contest] | tuple[Contest, ...], config: ContestFilter = _DEFAULT_FILTER
) -> tuple[ContestDecision, ...]:
    return tuple(evaluate_contest(item, config) for item in contests)


def _parse_rules(values: Any, group: str) -> tuple[ContestRule, ...]:
    if values is None:
        return ()
    if not isinstance(values, list):
        raise TypeError(f"{group} 必须为规则列表")
    rules = []
    for item in values:
        if not isinstance(item, dict):
            raise TypeError("比赛规则必须为表")
        pattern = item.get("pattern")
        enabled = item.get("enabled", True)
        if not isinstance(pattern, str) or not isinstance(enabled, bool):
            raise TypeError("比赛规则 pattern/enabled 字段类型无效")
        rules.append(ContestRule(pattern, enabled))
    return tuple(rules)


def filter_from_config(raw: Any) -> ContestFilter:
    """从配置的 contest_filter 表构造过滤器；兼容旧版 whitelist/blacklist 两组列表。"""
    if raw is None:
        return ContestFilter()
    if not isinstance(raw, dict):
        raise TypeError("contest_filter 必须为 TOML 表")
    excluded = raw.get("excluded", [])
    if not isinstance(excluded, list):
        raise TypeError("excluded 必须为列表")
    common = {
        "match_field": raw.get("match_field", "name"),
        "case_sensitive": raw.get("case_sensitive", False),
        "excluded": tuple(excluded),
    }
    if "rules" in raw or "mode" in raw:
        return ContestFilter(
            rules=_parse_rules(raw.get("rules", []), "rules"),
            mode=raw.get("mode", "blacklist"),
            **common,
        )
    whitelist = _parse_rules(raw.get("whitelist"), "whitelist")
    blacklist = _parse_rules(raw.get("blacklist"), "blacklist")
    if any(rule.enabled and rule.pattern for rule in whitelist):
        return ContestFilter(rules=whitelist, mode="whitelist", **common)
    return ContestFilter(rules=blacklist, mode="blacklist", **common)


def filter_to_config(config: ContestFilter) -> dict[str, Any]:
    return {
        "mode": config.mode,
        "match_field": config.match_field,
        "case_sensitive": config.case_sensitive,
        "rules": [{"pattern": rule.pattern, "enabled": rule.enabled} for rule in config.rules],
        "excluded": list(config.excluded),
    }


def toggle_excluded(contest: Contest, path=None) -> tuple[ContestFilter, bool]:
    """手动剔除 / 恢复一场比赛并写回配置；返回新的过滤器与「现在是否被剔除」。"""
    from dataclasses import replace

    current = load_contest_filter(path)
    key = contest_key(contest)
    excluded = tuple(item for item in current.excluded if item != key)
    removed = key not in current.excluded
    if removed:
        excluded += (key,)
    updated = replace(current, excluded=excluded)
    save_contest_filter(updated, path)
    return updated, removed


def load_contest_filter(path=None) -> ContestFilter:
    from ojaudit.core.config import load_config

    return filter_from_config(load_config(path).get("contest_filter"))


def save_contest_filter(config: ContestFilter, path=None):
    """保存规则并保留同一配置文件中的其他设置。"""
    from ojaudit.core.config import load_config, save_config

    current = load_config(path)
    current["contest_filter"] = filter_to_config(config)
    return save_config(current, path)
