"""
Module: Core / filters
Description: 比赛名称正则黑白名单与规则外手动打开。
Scope: Core
Notes: 黑名单优先于白名单；无启用白名单时显示全部。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ojaudit.core.schema import Contest


@dataclass(frozen=True, slots=True)
class ContestRule:
    pattern: str
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ContestFilter:
    whitelist: tuple[ContestRule, ...] = ()
    blacklist: tuple[ContestRule, ...] = ()
    match_field: Literal["name", "name_id"] = "name"
    case_sensitive: bool = False

    def __post_init__(self) -> None:
        if self.match_field not in {"name", "name_id"}:
            raise ValueError("比赛匹配字段必须为 name 或 name_id")
        if not isinstance(self.case_sensitive, bool):
            raise TypeError("case_sensitive 必须为布尔值")
        for rule in (*self.whitelist, *self.blacklist):
            if not isinstance(rule.pattern, str) or not isinstance(rule.enabled, bool):
                raise TypeError("比赛规则 pattern/enabled 字段类型无效")
            try:
                re.compile(rule.pattern, 0 if self.case_sensitive else re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"比赛筛选正则无效: {exc}") from exc


@dataclass(frozen=True, slots=True)
class ContestDecision:
    contest: Contest
    visible: bool
    outside_rules: bool
    reason: str


_DEFAULT_FILTER = ContestFilter()


def evaluate_contest(
    contest: Contest,
    config: ContestFilter = _DEFAULT_FILTER,
    manually_opened_id: str | None = None,
) -> ContestDecision:
    candidate = contest.name
    if config.match_field == "name_id":
        candidate += " " + contest.contest_id
    flags = 0 if config.case_sensitive else re.IGNORECASE

    def matches(rules: tuple[ContestRule, ...]) -> bool:
        return any(
            rule.enabled and bool(re.search(rule.pattern, candidate, flags)) for rule in rules
        )

    active_whitelist = tuple(rule for rule in config.whitelist if rule.enabled and rule.pattern)
    if matches(config.blacklist):
        return ContestDecision(contest, False, False, "命中黑名单")
    if not active_whitelist or matches(active_whitelist):
        return ContestDecision(contest, True, False, "符合筛选规则")
    if manually_opened_id == contest.contest_id:
        return ContestDecision(contest, True, True, "手动打开：规则外")
    return ContestDecision(contest, False, False, "未命中白名单")


def filter_contests(
    contests: list[Contest] | tuple[Contest, ...],
    config: ContestFilter = _DEFAULT_FILTER,
    manually_opened_id: str | None = None,
) -> tuple[ContestDecision, ...]:
    return tuple(evaluate_contest(item, config, manually_opened_id) for item in contests)


def load_contest_filter(path=None) -> ContestFilter:
    """从用户 TOML 的 contest_filter 表读取规则；非法规则拒绝加载。"""
    from ojaudit.core.config import load_config

    raw = load_config(path).get("contest_filter", {})
    if not isinstance(raw, dict):
        raise TypeError("contest_filter 必须为 TOML 表")

    def parse(group: str) -> tuple[ContestRule, ...]:
        values = raw.get(group, [])
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

    return ContestFilter(
        whitelist=parse("whitelist"),
        blacklist=parse("blacklist"),
        match_field=raw.get("match_field", "name"),
        case_sensitive=raw.get("case_sensitive", False),
    )


def save_contest_filter(config: ContestFilter, path=None):
    """保存规则并保留同一配置文件中的其他用户设置。"""
    from ojaudit.core.config import load_config, save_config

    current = load_config(path)
    current["contest_filter"] = {
        "match_field": config.match_field,
        "case_sensitive": config.case_sensitive,
        "whitelist": [
            {"pattern": rule.pattern, "enabled": rule.enabled} for rule in config.whitelist
        ],
        "blacklist": [
            {"pattern": rule.pattern, "enabled": rule.enabled} for rule in config.blacklist
        ],
    }
    return save_config(current, path)
