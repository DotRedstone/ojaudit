"""
Module: TODO Checker Test
Description: 验证任务注释格式检查规则。
Scope: Test
"""

from scripts.check_todos import check, validate_comment


def test_accepts_scoped_issue_comment():
    assert validate_comment("# TODO(detector): 增加边界测试 —— #123")


def test_rejects_bare_or_unscoped_markers():
    assert not validate_comment("# TODO later")
    assert not validate_comment("# FIXME: 有错误")
    assert not validate_comment("# XXX")


def test_repository_comments_are_valid():
    assert check() == []
