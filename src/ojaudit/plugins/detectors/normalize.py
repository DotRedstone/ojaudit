"""
Module: Detector / normalize
Description: 迁移旧检测器的 L1/L2/L3 代码归一化入口。
Scope: Detector
Notes: L3 规则与旧 nowcoder-collect 词法规则保持兼容。
"""

from ojaudit.plugins.detectors.nowcoder import normalize_tokens


def normalize(code: str, language: str) -> dict[str, object]:
    """返回旧检测器使用的三个归一化口径。"""
    import re

    return {
        "L1": code,
        "L2": re.sub(r"\s+", "", code),
        "L3": normalize_tokens(code, language),
    }
