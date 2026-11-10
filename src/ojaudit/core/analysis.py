"""
Module: Core / analysis
Description: 一次比赛分析的完整流程：读取配置与插件参数 → 排除管理者 → 运行内置检测 →
    写入 analysis_runs 与 findings。
Scope: Core
Notes:
- 参数按插件清单校验；配置中已废弃的参数键被忽略，而不是让分析失败。
- 优先级：命令行阈值 > 配置文件 > 清单默认值。
- 指纹、相似度、分级是必需阶段，配置中的 enabled 对它们无效；模板与时间线可关闭。
- 不打印、不访问网络；CLI 与 TUI 共用同一入口。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from ojaudit.core.config import load_config
from ojaudit.core.people import HiddenPerson, exclude_hidden_submissions
from ojaudit.core.plugins import PluginManifest, discover_manifests, validate_parameters
from ojaudit.core.store import Store
from ojaudit.plugins.detectors.engine import EngineConfig, analyze

REQUIRED = ("builtin_pair", "nowcoder_similarity", "nowcoder_classify")
OPTIONAL = ("nowcoder_template", "nowcoder_timeline")


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    run_id: str
    platform: str
    contest_id: str
    plugin_set: str
    findings: tuple[dict[str, Any], ...]


def detector_manifests() -> dict[str, PluginManifest]:
    directory = Path(str(resources.files("ojaudit.plugins"))) / "detectors"
    return {manifest.name: manifest for manifest in discover_manifests(directory)}


def engine_config(
    settings: Mapping[str, Any], threshold: float | None = None
) -> tuple[EngineConfig, tuple[str, ...]]:
    """由配置构造检测参数，返回 (参数, 启用的检测阶段)。"""
    detector = settings.get("detector", {})
    if isinstance(detector, Mapping) and not detector.get("enabled", True):
        raise ValueError("检测已在设置中禁用")
    plugins = settings.get("plugins", {})
    plugins = plugins if isinstance(plugins, Mapping) else {}
    manifests = detector_manifests()

    def section(name: str) -> Mapping[str, Any]:
        value = plugins.get(name, {})
        return value if isinstance(value, Mapping) else {}

    def params(name: str) -> dict[str, Any]:
        supplied = section(name).get("params", {})
        supplied = supplied if isinstance(supplied, Mapping) else {}
        manifest = manifests[name]
        return validate_parameters(
            manifest, {key: value for key, value in supplied.items() if key in manifest.params}
        )

    def enabled(name: str) -> bool:
        return bool(section(name).get("enabled", True))

    pair = params("builtin_pair")
    similarity = params("nowcoder_similarity")
    config = EngineConfig(
        threshold=float(pair["threshold"] if threshold is None else threshold),
        k=pair["k"],
        window=pair["window"],
        ngram_size=similarity["ngram_size"],
        rare_threshold=similarity["rare_threshold"],
        thresholds=params("nowcoder_classify"),
        enable_template=enabled("nowcoder_template"),
        enable_timeline=enabled("nowcoder_timeline"),
    )
    active = REQUIRED + tuple(name for name in OPTIONAL if enabled(name))
    return config, active


def run_analysis(
    store: Store,
    platform: str,
    contest_id: str,
    *,
    threshold: float | None = None,
    settings: Mapping[str, Any] | None = None,
    created_from: str = "cli",
) -> AnalysisResult:
    if not store.contest_exists(platform, contest_id):
        raise ValueError(f"比赛不存在：{platform}/{contest_id}；请先 collect 或 migrate")
    config, active = engine_config(settings if settings is not None else load_config(), threshold)
    hidden = tuple(HiddenPerson(**person) for person in store.list_hidden_people())
    submissions = exclude_hidden_submissions(store.submissions(platform, contest_id), hidden)
    findings = tuple(analyze(submissions, config))
    run_id = uuid.uuid4().hex
    plugin_set = "+".join(active)
    store.save_analysis(
        run_id,
        platform,
        contest_id,
        plugin_set,
        created_from,
        datetime.now(UTC).isoformat(),
        (
            {
                "uid_a": row["pair"][0],
                "uid_b": row["pair"][1],
                "problem_index": row["problem"],
                "language": row["language"],
                "level": row["verdict"],
                "scores": {
                    "similarity": row["similarity"],
                    **row["scores"],
                    "rare_score": row["rare"]["score"],
                    "template_crowd": row["crowd_count"],
                    "timeline": row["timeline"],
                },
                "reasons": row["reasons"],
            }
            for row in findings
        ),
    )
    return AnalysisResult(run_id, platform, contest_id, plugin_set, findings)
