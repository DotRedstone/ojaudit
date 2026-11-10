"""
Module: CLI / operations
Description: 牛客凭据保存、数据源构造与插件登记。
Scope: CLI
Notes: Cookie 文件权限 0600；第三方插件只登记，不导入执行。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from ojaudit.core.config import config_dir, load_config
from ojaudit.core.plugins import discover_manifests, parse_manifest
from ojaudit.plugins.sources.nowcoder import NowcoderSource


def cookie_file() -> Path:
    return config_dir() / "nowcoder.cookie"


def save_cookie(cookie: str) -> None:
    if not cookie.strip() or "\n" in cookie or "\r" in cookie:
        raise ValueError("Cookie 无效")
    path = cookie_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(cookie.strip())
    os.chmod(path, 0o600)


def nowcoder_source():
    config = load_config()
    settings = config.get("nowcoder", {})
    if not isinstance(settings, dict):
        raise TypeError("nowcoder 配置必须是表")
    settings = dict(settings)
    collect = config.get("collect", {})
    if not isinstance(collect, dict):
        raise TypeError("collect 配置必须是表")
    settings.update(
        {
            "phase": "all"
            if collect.get("include_after", False) and collect.get("phase", "contest") == "contest"
            else collect.get("phase", "contest"),
            "threads": collect.get("threads", 1),
            "retry_count": collect.get("retry_count", 2),
            "readonly": collect.get("readonly", True),
        }
    )
    if cookie_file().is_file():
        settings["cookie"] = cookie_file().read_text(encoding="utf-8").strip()
    return NowcoderSource(settings)


def plugin_registry() -> Path:
    return config_dir() / "plugins.json"


def plugins_command(action: str, spec: str | None = None) -> None:
    path = plugin_registry()
    registered = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if action == "list":
        for name, item in sorted(registered.items()):
            print(f"{name}\t{item['version']}\t{'enabled' if item['enabled'] else 'disabled'}")
        return
    if action == "install":
        if not spec or "@" not in spec:
            raise ValueError("install 需要 <git-url>@<rev>")
        url, rev = spec.rsplit("@", 1)
        if not re.fullmatch(r"[0-9a-f]{7,40}", rev):
            raise ValueError("必须固定 Git commit SHA")
        # 安全地使用临时目录检查 manifest，不执行插件代码或安装依赖。
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                ["git", "clone", "--quiet", "--no-checkout", "--", url, directory],
                check=True,
                timeout=60,
            )
            subprocess.run(
                ["git", "-C", directory, "checkout", "--detach", rev],
                check=True,
                timeout=30,
                capture_output=True,
            )
            manifests = discover_manifests(directory)
            root = Path(directory) / "plugin.toml"
            if root.is_file():
                manifests.append(parse_manifest(root.read_text(encoding="utf-8"), str(root)))
            if not manifests:
                raise ValueError("仓库未找到 plugin.toml")
            for manifest in manifests:
                registered[manifest.name] = {
                    "version": manifest.version,
                    "origin": f"{url}@{rev}",
                    "kind": manifest.kind,
                    "enabled": False,
                }
    else:
        if not spec or spec not in registered:
            raise ValueError("插件尚未登记")
        registered[spec]["enabled"] = action == "enable"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(registered, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    print(f"plugins {action}: ok (仅登记，不加载第三方代码)")
