"""
Module: User Configuration
Description: 读取和保存符合 XDG 约定的用户配置。
Scope: Core

Notes:
- 配置目录只存用户配置，不存采集数据库。
- 凭据不在普通 TOML 配置中明文保存。
"""

import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "ojaudit"


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser() / "ojaudit"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path).expanduser() if path else config_dir() / "config.toml"
    if not target.exists():
        return {}
    with target.open("rb") as stream:
        value = tomllib.load(stream)
    if not isinstance(value, dict):
        raise TypeError("配置根节点必须是 TOML 表")
    return value


def save_config(value: dict[str, Any], path: str | Path | None = None) -> Path:
    target = Path(path).expanduser() if path else config_dir() / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(tomli_w.dumps(value), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    return target
