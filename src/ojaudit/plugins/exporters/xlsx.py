"""
Module: Exporter / xlsx
Description: 将排行榜表格导出为 Excel 工作簿：中文表头、冻结首行与姓名列，按人员标记给整行着色。
Scope: Exporter
Notes:
- 展示哪些列、作弊者是否出现在表中由调用方（core.ranking / core.ranking_table）决定，
  导出器只负责呈现。
- 文本单元格以字符串写入，不会被 Excel 当作公式执行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_FILLS = {"cheater": "F8D7DA", "suspect": "FFF3CD", "manager": "E9ECEF"}
_WIDTHS = {"名次": 6, "姓名": 18, "UID": 14, "总分": 8, "标记": 8, "提交": 6, "最后得分": 10}


def export_xlsx(table: Any, destination: str | Path) -> Path:
    """table 为 core.ranking_table.RankingTable。"""
    book = Workbook()
    sheet = book.active
    sheet.title = str(table.title)[:31] or "排行榜"
    sheet.append(list(table.headers))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    text_columns = [i for i, kind in enumerate(table.kinds, 1) if kind == "text"]
    mark_column = table.mark_column
    for row, mark in zip(table.rows, table.marks):
        sheet.append(list(row))
        # 姓名等来自平台的文字强制按文本保存：以 = 开头的昵称不会变成公式。
        for column in text_columns:
            sheet.cell(sheet.max_row, column).data_type = "s"
        if mark in _FILLS:
            fill = PatternFill("solid", fgColor=_FILLS[mark])
            for cell in sheet[sheet.max_row]:
                cell.fill = fill
            if mark == "cheater" and mark_column is not None:
                sheet.cell(sheet.max_row, mark_column + 1).font = Font(bold=True, color="B02A37")
    for index, header in enumerate(table.headers, 1):
        width = _WIDTHS.get(header, 9 if "用时" in header else 7)
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "C2"
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    return path
