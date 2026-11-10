"""
Module: Test / core filters
Description: 黑名单 / 白名单两种模式、匹配字段、正则校验与旧配置兼容。
Scope: Test
Notes: 只使用合成比赛名。
"""

import pytest

from ojaudit.core.filters import (
    ContestFilter,
    ContestRule,
    evaluate_contest,
    filter_contests,
    filter_from_config,
    load_contest_filter,
    save_contest_filter,
)
from ojaudit.core.schema import Contest


def contest(cid="c1", name="Spring Open"):
    return Contest("synthetic", cid, name)


def test_default_shows_everything():
    assert all(d.visible for d in filter_contests([contest(), contest("c2", "Autumn")]))


def test_blacklist_hides_matches():
    rules = ContestFilter(rules=(ContestRule("open"),))
    assert not evaluate_contest(contest(), rules).visible
    assert evaluate_contest(contest("c2", "Autumn"), rules).visible
    disabled = ContestFilter(rules=(ContestRule("open", enabled=False),))
    assert evaluate_contest(contest(), disabled).visible


def test_whitelist_shows_only_matches_and_empty_shows_all():
    rules = ContestFilter(rules=(ContestRule("^Spring"),), mode="whitelist")
    assert evaluate_contest(contest(), rules).visible
    assert not evaluate_contest(contest("c2", "Autumn"), rules).visible
    assert evaluate_contest(contest("c2", "Autumn"), ContestFilter(mode="whitelist")).visible


def test_match_field_case_and_validation():
    rules = ContestFilter(rules=(ContestRule("C1"),), mode="whitelist", match_field="name_id")
    assert evaluate_contest(contest(), rules).visible
    strict = ContestFilter(rules=(ContestRule("spring"),), case_sensitive=True)
    assert evaluate_contest(contest(), strict).visible
    with pytest.raises(ValueError):
        ContestFilter(rules=(ContestRule("["),))
    with pytest.raises(ValueError):
        ContestFilter(mode="greylist")


def test_round_trip_and_legacy_config(tmp_path):
    path = tmp_path / "config.toml"
    config = ContestFilter(
        rules=(ContestRule("校内", True), ContestRule("外校", False)), mode="whitelist"
    )
    save_contest_filter(config, path)
    assert load_contest_filter(path) == config
    legacy_white = filter_from_config(
        {"whitelist": [{"pattern": "校内"}], "blacklist": [{"pattern": "外校"}]}
    )
    assert legacy_white.mode == "whitelist"
    assert [r.pattern for r in legacy_white.rules] == ["校内"]
    legacy_black = filter_from_config({"whitelist": [], "blacklist": [{"pattern": "外校"}]})
    assert (legacy_black.mode, legacy_black.rules[0].pattern) == ("blacklist", "外校")
