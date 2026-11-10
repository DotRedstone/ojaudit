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
from typing import Any

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
            "threads": collect.get("threads", 8),
            "retry_count": collect.get("retry_count", 2),
            "timeout": collect.get("timeout", 20),
            "rate_limit": collect.get("rate_limit", 0),
            "readonly": collect.get("readonly", True),
        }
    )
    if cookie_file().is_file():
        settings["cookie"] = cookie_file().read_text(encoding="utf-8").strip()
    return NowcoderSource(settings)


def known_codes(
    store: Any, platform: str, contest_id: str
) -> dict[str, tuple[str, str, str, float]]:
    """增量采集：本地已有源码的提交 {提交 ID: (代码, 语言, 结果, 得分)}；关闭增量时返回空。"""
    collect = load_config().get("collect", {})
    if isinstance(collect, dict) and not collect.get("incremental", True):
        return {}
    return {
        s.submission_id: (s.code, s.language, s.verdict, s.score)
        for s in store.submissions(platform, contest_id)
        if s.code.strip()
    }


def plugin_registry() -> Path:
    return config_dir() / "plugins.json"


# 只允许常见的仓库地址形式；拒绝 ext:: 等可执行命令的 git 传输协议。
_ALLOWED_URL = re.compile(r"^(?:https://|ssh://|file://|git@[\w.-]+:|/|\./|\.\./)")
# 禁止交互凭据提示、禁用危险协议、不跟随 hooks 与子模块。
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true", "GCM_INTERACTIVE": "never"}
_GIT_SAFE = ["-c", "protocol.ext.allow=never", "-c", "core.hooksPath=/dev/null"]


def _redact(url: str) -> str:
    """登记中的来源地址去掉 https://user:token@ 形式的凭据。"""
    return re.sub(r"^(https?://)[^/@]+@", r"\1", url)


def _git(*argv: str, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *_GIT_SAFE, *argv],
            check=True,
            timeout=timeout,
            capture_output=True,
            text=True,
            env={**os.environ, **_GIT_ENV},
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 git，请先安装 git") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git {argv[0]} 超时（{timeout} 秒）") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        raise RuntimeError(f"git {argv[0]} 失败：{detail[-1] if detail else exc}") from exc


def install_plugin(spec: str, registered: dict[str, dict[str, object]]) -> list[str]:
    """检出固定 commit 并校验清单后登记为禁用；不执行仓库中的任何代码。"""
    if not spec or "@" not in spec:
        raise ValueError("install 需要 <git-url>@<commit-sha>")
    url, rev = spec.rsplit("@", 1)
    if not re.fullmatch(r"[0-9a-f]{7,40}", rev):
        raise ValueError("必须固定 Git commit SHA（7–40 位小写十六进制）")
    if not _ALLOWED_URL.match(url):
        raise ValueError("仓库地址仅支持 https://、ssh://、git@host:、file:// 或本地路径")
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        _git("clone", "--quiet", "--no-checkout", "--", url, directory, timeout=120)
        _git("-C", directory, "checkout", "--quiet", "--detach", rev, timeout=30)
        head = _git("-C", directory, "rev-parse", "HEAD", timeout=10).stdout.strip()
        if not head.startswith(rev):
            raise ValueError(f"{rev} 不是 commit SHA（检出结果为 {head[:12]}）")
        manifests = discover_manifests(directory)
        root = Path(directory) / "plugin.toml"
        if root.is_file():
            manifests.append(parse_manifest(root.read_text(encoding="utf-8"), str(root)))
        if not manifests:
            raise ValueError("仓库未找到 plugin.toml")
    names = []
    for manifest in manifests:
        registered[manifest.name] = {
            "version": manifest.version,
            "origin": f"{_redact(url)}@{head}",
            "kind": manifest.kind,
            "enabled": False,
        }
        names.append(manifest.name)
    return names


def plugins_command(action: str, spec: str | None = None) -> None:
    path = plugin_registry()
    registered = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if action == "list":
        for name, item in sorted(registered.items()):
            state = "enabled" if item["enabled"] else "disabled"
            print(f"{name}\t{item['version']}\t{state}\t{item.get('origin', '')}")
        return
    if action == "install":
        # 任何失败都在写登记文件之前抛出，已有登记保持不变。
        install_plugin(spec or "", registered)
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
