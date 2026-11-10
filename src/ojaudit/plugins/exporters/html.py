"""
Module: Exporter / html
Description: 将审查线索与作弊者证据摘要导出为独立 HTML 报告。
Scope: Exporter
Notes: 所有外部字段均进行 HTML 转义；输出不加载远程资源。
"""

from __future__ import annotations

import html
import json
from collections.abc import Iterable
from pathlib import Path


def _value(value: object) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _pre(value: object) -> str:
    return html.escape(_value(value), quote=True)


def export_html(rows: Iterable[dict], destination: str | Path) -> Path:
    """导出稳定排序的审查报告；可选展示分数、时间线与代码对照。"""
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            str(row.get("problem", "")),
            str(row.get("language", "")),
            _value(row.get("pair", row.get("uid", ""))),
        ),
    )
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>ojaudit 审查报告</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;color:#202124;background:#fff}",
        "table{width:100%;border-collapse:collapse}th,td{padding:.55rem;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}",
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:.8rem;border-radius:.4rem}",
        ".evidence{border:1px solid #ddd;border-radius:.5rem;padding:1rem;margin:1rem 0}",
        ".code{display:grid;grid-template-columns:1fr 1fr;gap:1rem}",
        "@media(max-width:700px){.code{grid-template-columns:1fr}}",
        "</style></head><body>",
        "<h1>ojaudit 审查报告</h1>",
        f"<p>线索数量：{len(ordered)}</p>",
        "<table><thead><tr><th>题目</th><th>语言</th><th>对象</th><th>分数</th><th>等级</th><th>理由</th></tr></thead><tbody>",
    ]
    for row in ordered:
        pair = row.get("pair", row.get("uid", ""))
        parts.append(
            "<tr>"
            f"<td>{html.escape(_value(row.get('problem', '')))}</td>"
            f"<td>{html.escape(_value(row.get('language', '')))}</td>"
            f"<td>{html.escape(_value(pair))}</td>"
            f"<td>{html.escape(_value(row.get('scores', row.get('similarity', ''))))}</td>"
            f"<td>{html.escape(_value(row.get('mark', row.get('verdict', row.get('level', '')))))}</td>"
            f"<td>{html.escape(_value(row.get('reason', row.get('reasons', ''))))}</td>"
            "</tr>"
        )
    parts.extend(["</tbody></table>", "<h2>证据摘要</h2>"])
    for index, row in enumerate(ordered, 1):
        pair = row.get("pair", row.get("uid", ""))
        parts.extend(
            [
                '<section class="evidence">',
                f"<h3>#{index} · {html.escape(_value(pair))}</h3>",
                f"<p>分数：{_pre(row.get('scores', row.get('similarity', '')))}</p>",
                f"<p>时间线：{_pre(row.get('timeline', ''))}</p>",
                f"<p>理由：{_pre(row.get('reason', row.get('reasons', '')))}</p>",
                '<div class="code">',
                f"<div><h4>代码 A</h4><pre>{_pre(row.get('code_a', ''))}</pre></div>",
                f"<div><h4>代码 B</h4><pre>{_pre(row.get('code_b', ''))}</pre></div>",
                "</div></section>",
            ]
        )
    parts.append("</body></html>\n")
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
