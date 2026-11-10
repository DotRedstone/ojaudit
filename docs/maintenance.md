# 维护与验证

开发：`python -m pip install -e '.[dev]'`；验证：`ruff check .`、`ruff format --check .`、`python scripts/check_todos.py`、`pytest -q`。pytest 的源码布局由 `pythonpath = ["src", "."]` 声明。

Nix 开发环境：`nix develop`，测试：`nix flake check`；构建：`nix build .#default`。flake 输入由仓库内 `flake.lock` 固定。

回退以单阶段 PR 的 revert 为单位；用户数据迁移需独立验证且不得删除旧库。

路线图进度见 [roadmap.md](roadmap.md)。
