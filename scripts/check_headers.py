"""
Module: Header Checker
Description: 检查每个 Python 模块的头部 docstring 含 Module、Description、Scope 三项。
Scope: Core
Notes: 空的 __init__.py 不检查。
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("Module:", "Description:", "Scope:")


def check() -> list[str]:
    errors = []
    for folder in ("src", "tests", "scripts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if path.name == "__init__.py" and not source.strip():
                continue
            doc = ast.get_docstring(ast.parse(source)) or ""
            missing = [field for field in FIELDS if field not in doc]
            if missing:
                errors.append(f"{path.relative_to(ROOT)}: 缺少 {' '.join(missing)}")
    return errors


if __name__ == "__main__":
    problems = check()
    for problem in problems:
        print(problem)
    if problems:
        raise SystemExit(1)
    print("模块头部检查通过")
