"""
Module: TODO Checker
Description: 检查 Python 代码中的任务注释格式。
Scope: Core
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID = re.compile(r"^\s*#\s*(?:TODO|FIXME)\([a-z][a-z0-9-]*\):\s*.+\s+——\s+#\d+\s*$")
TOKEN = re.compile(r"\b(?:TODO|FIXME|XXX)\b")


def check() -> list[str]:
    errors = []
    for folder in ("src", "tests", "scripts", "examples"):
        base = ROOT / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") and TOKEN.search(stripped) and not VALID.fullmatch(line):
                    errors.append(f"{path.relative_to(ROOT)}:{number}: 非法 TODO/FIXME/XXX")
    return errors


if __name__ == "__main__":
    failures = check()
    if failures:
        raise SystemExit("\n".join(failures))
    print("任务注释格式检查通过")
