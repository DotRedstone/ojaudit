"""
Module: TODO Checker
Description: 检查 Python 注释中的任务标记格式。
Scope: Core
"""

import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID = re.compile(r"^(?:TODO|FIXME)\([a-z][a-z0-9-]*\):\s*.+\s+——\s+#\d+$")
MARKER = re.compile(r"\b(?:TODO|FIXME|XXX)\b")


def validate_comment(comment: str) -> bool:
    """验证 tokenize 返回的注释文本（不含行首空白）。"""
    body = comment[1:].strip()
    return not MARKER.search(body) or bool(VALID.fullmatch(body))


def check() -> list[str]:
    errors = []
    for folder in ("src", "tests", "scripts", "examples"):
        base = ROOT / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            try:
                tokens = tokenize.generate_tokens(io.StringIO(source).readline)
                for token in tokens:
                    if token.type == tokenize.COMMENT and not validate_comment(token.string):
                        errors.append(
                            f"{path.relative_to(ROOT)}:{token.start[0]}: 非法 TODO/FIXME/XXX"
                        )
            except (tokenize.TokenError, IndentationError) as exc:
                errors.append(f"{path.relative_to(ROOT)}: 无法解析 Python 注释: {exc}")
    return errors


if __name__ == "__main__":
    failures = check()
    if failures:
        raise SystemExit("\n".join(failures))
    print("任务注释格式检查通过")
