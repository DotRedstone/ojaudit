"""
Module: TUI / settings model
Description: 将已有配置接口及插件清单映射为可编辑选项。
Scope: TUI
Notes: 只保存非机密设置；不会读取或持久化 Cookie 与令牌。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from ojaudit.core.config import data_dir, load_config, save_config
from ojaudit.core.plugins import PluginManifest, discover_manifests, validate_parameters
from ojaudit.core.store import Store

CATEGORIES = (
    "账户",
    "比赛筛选",
    "人员名单",
    "采集",
    "检测",
    "插件管理",
    "外观",
    "快捷键",
    "关于",
)


@dataclass(frozen=True, slots=True)
class Option:
    category: str
    key: str
    title: str
    kind: str
    default: Any
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    readonly: bool = False
    description: str = ""

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(self.key.split("."))


STATIC_OPTIONS = (
    Option("账户", "account.cookie_env", "Cookie 环境变量名", "text", "NOWCODER_COOKIE"),
    Option(
        "比赛筛选", "contest_filter.match_field", "匹配字段", "enum", "name", ("name", "name_id")
    ),
    Option("比赛筛选", "contest_filter.case_sensitive", "区分大小写", "bool", False),
    Option("比赛筛选", "contest_filter.whitelist_pattern", "白名单正则（单条）", "text", ""),
    Option("比赛筛选", "contest_filter.blacklist_pattern", "黑名单正则（单条）", "text", ""),
    Option("人员名单", "people.platform", "管理者所属平台", "text", "nowcoder"),
    Option("人员名单", "people.manager_uids", "管理者 UID（逗号分隔）", "text", ""),
    Option("采集", "collect.phase", "采集阶段", "enum", "contest", ("contest", "after", "all")),
    Option("采集", "collect.retry_count", "失败重试次数", "int", 2, minimum=0, maximum=10),
    Option("采集", "collect.readonly", "只读采集", "bool", True),
    Option("检测", "detector.enabled", "启用检测", "bool", True),
    Option(
        "外观",
        "appearance.theme",
        "主题",
        "enum",
        "auto",
        ("auto", "wallpaper", "ansi-dark", "catppuccin-mocha", "nord", "gruvbox", "textual-dark"),
    ),
    Option("外观", "appearance.compact", "紧凑列表", "bool", True),
    Option("外观", "appearance.key_hints", "显示按键提示", "bool", True),
    Option("外观", "appearance.nerd_font", "使用 Nerd Font 图标", "bool", False),
    Option(
        "快捷键",
        "help.keys",
        "快捷键",
        "text",
        "j/k 上下，Enter 进入，Esc 返回，Ctrl+S 保存",
        readonly=True,
    ),
    Option("关于", "help.version", "当前版本", "text", "ojaudit 0.1.dev", readonly=True),
)


def _get(data: dict[str, Any], path: tuple[str, ...], default: Any) -> Any:
    if path in (
        ("contest_filter", "whitelist_pattern"),
        ("contest_filter", "blacklist_pattern"),
    ):
        group = path[-1].removesuffix("_pattern")
        rules = data.get("contest_filter", {}).get(group, [])
        return rules[0].get("pattern", "") if isinstance(rules, list) and rules else ""
    current: Any = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _set(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    if path in (
        ("contest_filter", "whitelist_pattern"),
        ("contest_filter", "blacklist_pattern"),
    ):
        re.compile(value)
        group = path[-1].removesuffix("_pattern")
        filters = data.setdefault("contest_filter", {})
        old = filters.get(group, [])
        remainder = old[1:] if isinstance(old, list) else []
        filters[group] = ([{"pattern": value, "enabled": True}] if value else []) + remainder
        return
    current = data
    for part in path[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[path[-1]] = value


def plugin_manifests(directory: str | Path | None = None) -> list[PluginManifest]:
    if directory is None:
        directory = Path(str(resources.files("ojaudit.plugins"))) / "detectors"
    return discover_manifests(directory)


def generated_options(manifests: list[PluginManifest]) -> tuple[Option, ...]:
    options = list(STATIC_OPTIONS)
    for manifest in manifests:
        plugin = manifest.name
        options.append(
            Option(
                "插件管理",
                f"plugins.{plugin}.enabled",
                f"{plugin} · 启用",
                "bool",
                False,
                description=f"版本 {manifest.version} · {manifest.origin}",
            )
        )
        if manifest.kind.startswith("detector."):
            options.append(
                Option(
                    "检测",
                    f"plugins.{plugin}.enabled",
                    f"{plugin} · 启用",
                    "bool",
                    False,
                    description=manifest.description,
                )
            )
            for key, spec in manifest.params.items():
                if not isinstance(spec, dict) or "type" not in spec:
                    continue
                kind = str(spec["type"])
                options.append(
                    Option(
                        "检测",
                        f"plugins.{plugin}.params.{key}",
                        str(spec.get("label", key)),
                        kind,
                        spec.get("default"),
                        tuple(str(x) for x in spec.get("choices", ())),
                        spec.get("min"),
                        spec.get("max"),
                        description=f"{plugin}: {manifest.description}",
                    )
                )
    options.append(
        Option(
            "插件管理",
            "help.install",
            "安装新插件（暂不联网）",
            "text",
            "目前只展示已安装插件",
            readonly=True,
        )
    )
    return tuple(options)


class SettingsModel:
    def __init__(
        self,
        path: str | Path | None = None,
        manifests: list[PluginManifest] | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self.path = path
        self.db_path = Path(db_path) if db_path is not None else data_dir() / "ojaudit.sqlite"
        self.manifests = manifests if manifests is not None else plugin_manifests()
        self.options = generated_options(self.manifests)
        self.saved = load_config(path)
        platform = str(_get(self.saved, ("people", "platform"), "nowcoder"))
        self._original_platform = platform
        self._original_managers = self._read_managers(platform)
        _set(self.saved, ("people", "manager_uids"), ",".join(sorted(self._original_managers)))
        self.values = {opt.key: _get(self.saved, opt.path, opt.default) for opt in self.options}

    def _read_managers(self, platform: str) -> set[str]:
        if not self.db_path.is_file():
            return set()
        connection = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return {
                str(row[0])
                for row in connection.execute(
                    "SELECT uid FROM hidden_people WHERE platform=?", (platform,)
                )
            }
        finally:
            connection.close()

    def options_for(self, category: str) -> list[Option]:
        return [opt for opt in self.options if opt.category == category]

    def changed(self, option: Option) -> bool:
        return self.values[option.key] != _get(self.saved, option.path, option.default)

    @property
    def dirty(self) -> bool:
        return any(self.changed(option) for option in self.options if not option.readonly)

    def change(self, option: Option, value: Any) -> None:
        if option.readonly:
            raise ValueError("只读设置")
        if option.kind == "bool" and not isinstance(value, bool):
            raise TypeError("开关需使用布尔值")
        if option.kind == "enum" and value not in option.choices:
            raise ValueError("无效选项")
        if option.kind in {"int", "float"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("数值类型无效")
            if option.kind == "int" and not isinstance(value, int):
                raise TypeError("请输入整数")
            if option.minimum is not None and value < option.minimum:
                raise ValueError("低于允许的最小值")
            if option.maximum is not None and value > option.maximum:
                raise ValueError("超出允许的最大值")
        if option.kind in {"text", "str"} and not isinstance(value, str):
            raise TypeError("文本类型无效")
        self.values[option.key] = value

    def restore(self, category: str) -> None:
        for option in self.options_for(category):
            if not option.readonly:
                self.values[option.key] = option.default

    def save(self) -> None:
        config = load_config(self.path)
        manager_changed = self.values["people.manager_uids"] != ",".join(
            sorted(self._original_managers)
        )
        platform = self.values["people.platform"]
        if manager_changed and platform != self._original_platform:
            raise ValueError("切换人员平台后请先保存平台，再单独编辑管理者名单")
        incoming = {
            uid.strip() for uid in self.values["people.manager_uids"].split(",") if uid.strip()
        }
        if manager_changed and not self.db_path.is_file():
            raise ValueError("本地数据库不存在，不能创建管理者名单")

        for option in self.options:
            if option.readonly:
                continue
            # 未更改的值不回写，避免破坏其他模块的原始配置结构。
            if not self.changed(option):
                continue
            _set(config, option.path, self.values[option.key])
        for manifest in self.manifests:
            specs = {
                key: self.values[f"plugins.{manifest.name}.params.{key}"]
                for key, spec in manifest.params.items()
                if isinstance(spec, dict) and f"plugins.{manifest.name}.params.{key}" in self.values
            }
            if specs:
                validate_parameters(manifest, specs)
        if manager_changed:
            with Store(self.db_path) as store:
                for uid in sorted(self._original_managers - incoming):
                    store.remove_hidden_person(platform, uid)
                for uid in sorted(incoming - self._original_managers):
                    store.put_hidden_person(platform, uid)
        save_config(config, self.path)
        self.saved = load_config(self.path)
        self._original_platform = platform
        self._original_managers = incoming if manager_changed else self._read_managers(platform)
        _set(self.saved, ("people", "manager_uids"), ",".join(sorted(self._original_managers)))
        self.values["people.manager_uids"] = ",".join(sorted(self._original_managers))
