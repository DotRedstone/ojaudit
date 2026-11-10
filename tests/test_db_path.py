"""
Module: Test / database path
Description: 数据库路径优先级，以及 CLI 与 TUI 打开同一数据库。
Scope: Test
Notes: 只使用合成数据，不访问网络。
"""

from ojaudit.cli import _parser
from ojaudit.tui.app import AuditApp
from ojaudit.tui.settings_model import SettingsModel


def test_explicit_db_path_reaches_tui(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    database = tmp_path / "custom.sqlite"
    args = _parser().parse_args(["--db", str(database)])
    app = AuditApp(db_path=args.db)
    assert app.contests.db_path == database
    model = SettingsModel(db_path=app.contests.db_path, manifests=[])
    assert model.db_path == database
    assert any(option.key == "storage.sqlite_path" for option in model.options)


def test_configured_path_and_cli_override(tmp_path, monkeypatch):
    from ojaudit.core.config import save_config

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    configured = tmp_path / "configured.sqlite"
    explicit = tmp_path / "explicit.sqlite"
    save_config({"storage": {"sqlite_path": str(configured)}})
    assert AuditApp().contests.db_path == configured
    assert AuditApp(db_path=explicit).contests.db_path == explicit
    assert _parser().parse_args([]).db is None
