"""
Module: TUI / shared components
Description: 提供统一的语义颜色行与左侧强调标记。
Scope: TUI
Notes: 颜色始终由主题 TCSS 变量决定，不在业务代码内写死色值。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from textual.widgets import Label

from ojaudit.tui.interaction import NavigateListItem


def row_kind(row: Mapping[str, Any]) -> str:
    """根据已有审核元数据选取语义 class，不改变审查结论。"""
    if row.get("is_stale"):
        return "mark-manager"
    if row.get("hidden") or row.get("person_mark") == "manager":
        return "mark-manager"
    mark = str(row.get("mark") or row.get("person_mark") or "")
    if mark in {"cheater", "suspect", "normal"}:
        return f"mark-{mark}"
    level = str(row.get("verdict_level") or "").lower()
    if level in {"high", "medium", "low"}:
        return f"level-{level}"
    return ""


class StatusRow(NavigateListItem):
    """所有列表共用的竖条、焦点和状态色容器。"""

    def __init__(self, text: str, *, kind: str = "") -> None:
        classes = f"status-row {kind}".strip()
        super().__init__(Label(text), classes=classes)
