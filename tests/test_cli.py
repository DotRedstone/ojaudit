"""
Module: CLI Smoke Test
Description: 验证开发阶段命令入口可调用。
Scope: Test
"""

from ojaudit.cli import main


def test_cli_smoke(capsys):
    main([])
    assert "仓库骨架阶段" in capsys.readouterr().out
