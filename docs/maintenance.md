# 维护与验证

开发：`python -m pip install -e '.[dev]'`；验证：`ruff check .`、`pytest`、`python scripts/check_todos.py`。Nix 开发环境：`nix develop`，测试：`nix flake check`。回退以单阶段 PR 的 revert 为单位；用户数据迁移需独立验证且不得删除旧库。
