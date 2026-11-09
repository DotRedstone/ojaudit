"""
Module: TODO Checker Test
Description: 验证任务注释格式检查规则。
Scope: Test
"""

from pathlib import Path

from scripts.check_todos import check


def test_repository_todos_are_valid():
    assert check() == []


def test_checker_exists():
    assert Path("scripts/check_todos.py").is_file()
