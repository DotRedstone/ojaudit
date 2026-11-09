"""
Module: CLI Smoke Test
Description: 验证命令行参数和帮助输出。
Scope: Test
"""

import pytest

from ojaudit.cli import main


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "analyze" in capsys.readouterr().out
