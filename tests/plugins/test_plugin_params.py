"""
Module: Builtin Plugin Parameter Tests
Description: 验证内置插件清单可加载，参数默认值与实现保持一致。
Scope: Test
"""

import ast
import inspect
from pathlib import Path

import pytest

from ojaudit.core.plugins import discover_manifests, validate_parameters
from ojaudit.plugins.detectors import nowcoder, similarity, template

ROOT = Path(__file__).parents[2] / "src" / "ojaudit" / "plugins"


def _manifests(group):
    return {item.name: item for item in discover_manifests(ROOT / group)}


def _default(function, name):
    return inspect.signature(function).parameters[name].default


def _thresholds_from_code():
    source = inspect.getsource(nowcoder)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "thresholds"
                for target in node.targets
            )
            and isinstance(node.value, ast.Dict)
        ):
            result = {}
            for key, value in zip(node.value.keys, node.value.values):
                if key is not None:
                    result[ast.literal_eval(key)] = ast.literal_eval(value)
            return result
    raise AssertionError("未找到旧检测器阈值默认值")


def test_all_eight_builtin_manifests_are_discoverable():
    detectors = _manifests("detectors")
    exporters = _manifests("exporters")
    assert set(detectors) == {
        "nowcoder_normalize",
        "nowcoder_similarity",
        "nowcoder_template",
        "nowcoder_timeline",
        "nowcoder_classify",
    }
    assert set(exporters) == {"builtin_csv", "builtin_markdown", "builtin_html"}
    assert all(item.api_version == 1 for item in (*detectors.values(), *exporters.values()))


def test_detector_parameter_defaults_match_implementation():
    detectors = _manifests("detectors")
    assert validate_parameters(detectors["nowcoder_normalize"], {}) == {}
    assert validate_parameters(detectors["nowcoder_timeline"], {}) == {}
    similarity_params = validate_parameters(detectors["nowcoder_similarity"], {})
    assert similarity_params == {
        "ngram_size": _default(similarity.build_rare_sets, "size"),
        "rare_threshold": _default(similarity.build_rare_sets, "rare_threshold"),
    }
    template_params = validate_parameters(detectors["nowcoder_template"], {})
    assert template_params == {
        "ngram_size": _default(template.common_ratio, "size"),
        "rare_threshold": _default(template.common_ratio, "rare_threshold"),
        "crowd_threshold": _default(template.exclude_crowd_template, "threshold"),
    }
    assert validate_parameters(detectors["nowcoder_classify"], {}) == _thresholds_from_code()


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
