"""
Module: Contest Filter Tests
Description: 验证正则白黑名单优先级、规则启停、持久化和规则外手动打开。
Scope: Test
"""

import pytest

from ojaudit.core.filters import (
    ContestFilter,
    ContestRule,
    evaluate_contest,
    filter_contests,
    load_contest_filter,
    save_contest_filter,
)
from ojaudit.core.schema import Contest


def contest(contest_id="c1", name="Spring Open"):
    return Contest("synthetic", contest_id, name)


def test_blacklist_precedes_whitelist_and_manual_open():
    rules = ContestFilter(whitelist=(ContestRule("Spring"),), blacklist=(ContestRule("Open"),))
    result = evaluate_contest(contest(), rules, manually_opened_id="c1")
    assert (result.visible, result.outside_rules, result.reason) == (False, False, "命中黑名单")


def test_empty_or_disabled_whitelist_means_show_all():
    rules = ContestFilter(whitelist=(ContestRule("never", enabled=False),))
    assert all(
        item.visible for item in filter_contests([contest(), contest("c2", "Autumn")], rules)
    )


def test_name_id_matching_case_and_manual_open():
    rules = ContestFilter(
        match_field="name_id", case_sensitive=False, whitelist=(ContestRule("C1"),)
    )
    assert evaluate_contest(contest(), rules).visible
    outside = evaluate_contest(contest("c3", "Autumn"), rules, manually_opened_id="c3")
    assert outside.visible and outside.outside_rules


def test_invalid_regex_and_field_are_rejected():
    with pytest.raises(ValueError, match="正则无效"):
        ContestFilter(whitelist=(ContestRule("["),))
    with pytest.raises(ValueError):
        ContestFilter(match_field="unknown")


def test_blacklisted_contest_cannot_be_manually_opened():
    rules = ContestFilter(blacklist=(ContestRule("Spring"),))
    assert not evaluate_contest(contest(), rules, manually_opened_id="c1").visible


def test_filter_settings_roundtrip_preserves_other_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('theme = "dark"\n', encoding="utf-8")
    config = ContestFilter(
        whitelist=(ContestRule("校内", True),),
        blacklist=(ContestRule("外校", False),),
        match_field="name_id",
        case_sensitive=True,
    )
    save_contest_filter(config, path)
    assert load_contest_filter(path) == config
    assert 'theme = "dark"' in path.read_text(encoding="utf-8")
