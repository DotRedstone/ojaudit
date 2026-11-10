"""
Module: Detector Manifest Tests
Description: 验证五个迁移检测模块均有可发现的插件清单。
Scope: Test
"""

from pathlib import Path

from ojaudit.core.plugins import discover_manifests


def test_five_legacy_detector_plugins_have_manifests():
    root = Path(__file__).parents[2] / "src" / "ojaudit" / "plugins" / "detectors"
    manifests = discover_manifests(root)
    by_name = {item.name: item for item in manifests}
    assert set(by_name) == {
        "nowcoder_normalize",
        "nowcoder_similarity",
        "nowcoder_template",
        "nowcoder_timeline",
        "nowcoder_classify",
    }
    assert by_name["nowcoder_classify"].kind == "detector.classifier"
    assert all(item.api_version == 1 for item in manifests)
