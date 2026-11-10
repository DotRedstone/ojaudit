"""
Module: Builtin Plugin Parameter Tests
Description: 验证内置插件清单可加载，参数默认值与实现保持一致。
Scope: Test
"""

from pathlib import Path

import pytest

from ojaudit.core.plugins import discover_manifests, validate_parameters
from ojaudit.plugins.detectors.classify import DEFAULT_THRESHOLDS
from ojaudit.plugins.detectors.engine import EngineConfig

ROOT = Path(__file__).parents[2] / "src" / "ojaudit" / "plugins"


def _manifests(group):
    return {item.name: item for item in discover_manifests(ROOT / group)}


def test_builtin_manifests_are_discoverable():
    detectors = _manifests("detectors")
    exporters = _manifests("exporters")
    assert set(detectors) == {
        "builtin_pair",
        "nowcoder_similarity",
        "nowcoder_template",
        "nowcoder_timeline",
        "nowcoder_classify",
    }
    assert set(exporters) == {"builtin_csv", "builtin_markdown", "builtin_html", "builtin_xlsx"}
    assert all(item.api_version == 1 for item in (*detectors.values(), *exporters.values()))


def test_detector_parameter_defaults_match_implementation():
    detectors = _manifests("detectors")
    defaults = EngineConfig()
    assert validate_parameters(detectors["builtin_pair"], {}) == {
        "threshold": defaults.threshold,
        "k": defaults.k,
        "window": defaults.window,
    }
    assert validate_parameters(detectors["nowcoder_similarity"], {}) == {
        "ngram_size": defaults.ngram_size,
        "rare_threshold": defaults.rare_threshold,
    }
    assert validate_parameters(detectors["nowcoder_template"], {}) == {}
    assert validate_parameters(detectors["nowcoder_timeline"], {}) == {}
    assert validate_parameters(detectors["nowcoder_classify"], {}) == DEFAULT_THRESHOLDS


def test_exporters_have_no_unsupported_parameters():
    for manifest in _manifests("exporters").values():
        assert manifest.kind == "exporter"
        assert validate_parameters(manifest, {}) == {}


def test_parameter_type_and_range_validation():
    manifest = _manifests("detectors")["nowcoder_similarity"]
    with pytest.raises(TypeError):
        validate_parameters(manifest, {"ngram_size": True})
    with pytest.raises(ValueError):
        validate_parameters(manifest, {"ngram_size": 0})
    with pytest.raises(ValueError):
        validate_parameters(manifest, {"unknown": 1})
