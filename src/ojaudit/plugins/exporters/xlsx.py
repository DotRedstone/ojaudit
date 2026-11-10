"""
Module: Exporter / xlsx
Description: 将最终排名导出为 Excel 工作簿：中文表头、冻结首行，按人员标记给整行着色。
Scope: Exporter
Notes:
- 作弊者是否出现在表中由排名策略决定（标记 / 除名），导出器只负责呈现。
- 文本单元格以字符串写入，不会被 Excel 当作公式执行。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_COLUMNS = (
    ("rank", "名次"),
    ("name", "姓名"),
    ("uid", "UID"),
    ("score", "得分"),
    ("person_mark", "标记"),
)
_MARKS = {"cheater": "作弊", "suspect": "存疑", "manager": "管理者"}
_FILLS = {"cheater": "F8D7DA", "suspect": "FFF3CD", "manager": "E9ECEF"}


def export_xlsx(rows: Iterable[dict], destination: str | Path, title: str = "排行榜") -> Path:
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (int(row.get("rank", 0)), str(row.get("uid", ""))),
    )
    book = Workbook()
    sheet = book.active
    sheet.title = title[:31]
    sheet.append([name for _, name in _COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    for row in ordered:
        mark = str(row.get("person_mark", "") or "")
        sheet.append(
            [
                int(row.get("rank", 0)),
                str(row.get("name", "")),
                str(row.get("uid", "")),
                float(row.get("score", 0)),
                _MARKS.get(mark, ""),
            ]
        )
        # 姓名等来自平台的文字强制按文本保存：以 = 开头的昵称不会变成公式。
        for column in (2, 3, 5):
            sheet.cell(sheet.max_row, column).data_type = "s"
        if mark in _FILLS:
            fill = PatternFill("solid", fgColor=_FILLS[mark])
            for cell in sheet[sheet.max_row]:
                cell.fill = fill
            if mark == "cheater":
                sheet.cell(sheet.max_row, 5).font = Font(bold=True, color="B02A37")
    for index, width in enumerate((6, 18, 14, 8, 8), 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    return path
