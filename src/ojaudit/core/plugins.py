"""
Module: Plugin Registry
Description: 校验插件清单并发现已安装的插件元信息。
Scope: Core

Notes:
- 发现插件不等于执行插件；第三方代码默认禁用。
- 只有显式启用且版本锁定后，后续运行阶段才允许加载入口点。
"""

import re
import tomllib
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

_PLUGIN_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_ALLOWED_KINDS = {
    "source", "detector.pair", "detector.single", "detector.classifier", "exporter"
}


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    kind: str
    version: str
    api_version: int
    description: str
    languages: tuple[str, ...]
    params: dict[str, Any]
    origin: str


def parse_manifest(content: str, origin: str = "unknown") -> PluginManifest:
    raw = tomllib.loads(content)
    required = ("name", "kind", "version", "api_version", "description")
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"插件清单缺少字段: {', '.join(missing)}")
    if not _PLUGIN_NAME.fullmatch(raw["name"]):
        raise ValueError("插件名称格式无效")
    if raw["kind"] not in _ALLOWED_KINDS:
        raise ValueError("插件类型不受支持")
    if raw["api_version"] != 1:
        raise ValueError("插件 API 版本不兼容")
    if not isinstance(raw["version"], str) or not raw["version"]:
        raise ValueError("插件版本不能为空")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        raise TypeError("params 必须是 TOML 表")
    return PluginManifest(
        name=raw["name"],
        kind=raw["kind"],
        version=raw["version"],
        api_version=raw["api_version"],
        description=raw["description"],
        languages=tuple(raw.get("languages", ())),
        params=params,
        origin=origin,
    )


def discover_manifests(directory: str | Path) -> list[PluginManifest]:
    manifests = []
    for path in sorted(Path(directory).glob("*/plugin.toml")):
        manifests.append(parse_manifest(path.read_text(encoding="utf-8"), str(path)))
    return manifests


def discover_entry_points() -> list[tuple[str, str]]:
    return sorted((point.name, point.value) for point in entry_points(group="ojaudit.plugins"))


def validate_parameters(manifest: PluginManifest, supplied: dict[str, Any]) -> dict[str, Any]:
    result = {}
    unknown = set(supplied) - set(manifest.params)
    if unknown:
        raise ValueError(f"未知插件参数: {', '.join(sorted(unknown))}")
    for name, spec in manifest.params.items():
        if not isinstance(spec, dict) or "type" not in spec:
            raise ValueError(f"参数 {name} 缺少类型定义")
        value = supplied.get(name, spec.get("default"))
        kind = spec["type"]
        if kind == "int":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif kind == "float":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif kind == "bool":
            valid = isinstance(value, bool)
        elif kind == "str":
            valid = isinstance(value, str)
        elif kind == "enum":
            valid = value in spec.get("choices", [])
        else:
            raise ValueError(f"参数 {name} 使用未知类型 {kind}")
        if not valid:
            raise TypeError(f"参数 {name} 的值或类型无效")
        if "min" in spec and value < spec["min"]:
            raise ValueError(f"参数 {name} 小于最小值")
        if "max" in spec and value > spec["max"]:
            raise ValueError(f"参数 {name} 大于最大值")
        result[name] = value
    return result
