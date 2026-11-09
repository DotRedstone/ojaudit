"""
Module: Plugin Tests
Description: 验证插件清单与参数约束。
Scope: Test
"""

import pytest

from ojaudit.core.plugins import parse_manifest, validate_parameters


def test_manifest_and_parameters():
    manifest = parse_manifest('''
name = "demo_detector"
kind = "detector.pair"
version = "1.0.0"
api_version = 1
description = "合成检测器"
[params.k]
type = "int"
default = 5
min = 3
max = 8
''')
    assert validate_parameters(manifest, {}) == {"k": 5}
    with pytest.raises(ValueError):
        validate_parameters(manifest, {"k": 20})


def test_manifest_rejects_unknown_api():
    with pytest.raises(ValueError):
        parse_manifest('name="x"\nkind="source"\nversion="1"\napi_version=2\ndescription="x"')
