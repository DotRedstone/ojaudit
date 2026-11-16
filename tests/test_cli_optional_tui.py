"""
Module: CLI Optional TUI Test
Description: 验证未安装 TUI 依赖时核心命令仍可执行，裸命令给出安装提示。
Scope: Test
Notes: 用子进程 + 导入钩子模拟 textual 与 ojaudit.tui 缺失；不在父进程改动 sys.modules，
       避免污染其他测试的模块身份。
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 把 textual 与 ojaudit.tui 变成不可导入，模拟「只装了核心依赖」的安装形态。
_BLOCKER = textwrap.dedent(
    """
    import sys

    _BLOCKED_ROOTS = {"textual"}
    _BLOCKED_PREFIX = "ojaudit.tui"

    class _Blocker:
        def find_spec(self, name, path=None, target=None):
            root = name.split(".")[0]
            if root in _BLOCKED_ROOTS or name == _BLOCKED_PREFIX or name.startswith(
                _BLOCKED_PREFIX + "."
            ):
                # name 保留完整模块名，与真实的 ModuleNotFoundError 语义一致。
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return None

    sys.meta_path.insert(0, _Blocker())
    """
)


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    script = _BLOCKER + "\nfrom ojaudit.cli import main\nmain(" + repr(list(args)) + ")\n"
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
        env=env,
        timeout=120,
    )


def test_help_works_without_tui():
    result = _run_cli("--help")
    assert result.returncode == 0
    assert "analyze" in result.stdout


def test_bare_command_hints_tui_extra():
    result = _run_cli()
    assert result.returncode != 0
    assert "ojaudit[tui]" in result.stderr


def test_core_command_runs_without_tui(tmp_path):
    """contests 是纯核心命令，不得因缺少 TUI 依赖而失败。"""
    db = tmp_path / "ojaudit.sqlite"
    result = _run_cli("--db", str(db), "contests")
    assert result.returncode == 0, result.stderr
    assert "textual" not in result.stderr.lower()


def test_login_qr_hints_tui_extra():
    """扫码登录当前复用 TUI 包内的服务层，缺依赖时给出同一安装提示。"""
    result = _run_cli("login", "--qr")
    assert result.returncode != 0
    assert "ojaudit[tui]" in result.stderr
