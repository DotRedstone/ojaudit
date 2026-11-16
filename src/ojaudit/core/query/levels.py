"""
Module: Core / query / levels
Description: 检测等级、人物标记与题号/时间的展示语义；与终端渲染无关。
Scope: Core
Notes: 等级既可能是中文分级，也可能是插件输出的 high/medium/low；rank 越小越优先复核。
"""

from __future__ import annotations

from datetime import datetime

# 检测等级：旧检测器输出中文分级，示例数据和外部插件可能输出 high/medium/low。
# rank 越小越需要优先复核；未知等级排在最后。
_LEVELS: dict[str, tuple[str, int]] = {
    "实锤": ("实锤", 0),
    "high": ("高", 0),
    "中偏强": ("中偏强", 1),
    "medium": ("中", 1),
    "存疑": ("存疑", 2),
    "low": ("低", 2),
    "排除": ("排除", 3),
}
MARK_NAMES = {"normal": "正常", "suspect": "存疑", "cheater": "作弊者"}
LEVEL_WEIGHT = {0: 3, 1: 2, 2: 1}


def problem_label(index: object) -> str:
    """题号显示为 A、B、…、Z、AA（与比赛页面一致）。"""
    try:
        number = int(index)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return str(index)
    label = ""
    number += 1
    while number > 0:
        number, rest = divmod(number - 1, 26)
        label = chr(ord("A") + rest) + label
    return label


def level_weight(level: object) -> int:
    """人物对嫌疑度的计分：实锤 3、中偏强 2、存疑 1。"""
    return LEVEL_WEIGHT.get(level_rank(level), 0)


def level_rank(level: object) -> int:
    return _LEVELS.get(str(level).strip().lower(), _LEVELS.get(str(level), ("", 9)))[1]


def level_name(level: object) -> str:
    raw = str(level).strip()
    return _LEVELS.get(raw.lower(), _LEVELS.get(raw, (raw, 9)))[0]


def is_high_priority(level: object) -> bool:
    return level_rank(level) <= 1


def percent(value: object) -> str:
    try:
        return f"{float(value):.0%}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)


def clock(timestamp: object) -> str:
    """提交时间统一为毫秒；过小的值视为合成或相对时间，原样显示。"""
    try:
        value = int(timestamp)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return str(timestamp)
    if value < 10**11:
        return str(value)
    return datetime.fromtimestamp(value / 1000).astimezone().strftime("%m-%d %H:%M:%S")


def duration(seconds: object) -> str:
    try:
        total = round(float(seconds))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} 时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"
