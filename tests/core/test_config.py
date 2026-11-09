"""
Module: Config Tests
Description: 验证 TOML 配置的安全写入与读取。
Scope: Test
"""

from ojaudit.core.config import load_config, save_config


def test_config_round_trip_and_permissions(tmp_path):
    path = tmp_path / "config.toml"
    save_config({"contest": {"include": ["^demo"]}}, path)
    assert load_config(path) == {"contest": {"include": ["^demo"]}}
    assert path.stat().st_mode & 0o777 == 0o600
