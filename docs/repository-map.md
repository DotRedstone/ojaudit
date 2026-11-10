# 仓库改动路由

| 改动 | 先读 | 目标位置 | 验证 |
| --- | --- | --- | --- |
| 打包与入口 | README、pyproject | pyproject.toml、src/ojaudit/cli.py | 安装、ojaudit --help |
| TODO 规则 | AGENTS、roadmap | scripts/check_todos.py、CI | python scripts/check_todos.py |
| 数据模型 | data-model.md | src/ojaudit/core/ | pytest |
| 插件接口 | plugin-api.md | src/ojaudit/core/、plugins/ | pytest |
| 检测 | detection.md | src/ojaudit/plugins/detectors/ | pytest |
| TUI | tui.md | src/ojaudit/tui/ | pytest |
| 发布 | maintenance.md | pyproject.toml、flake.nix、CI | nix flake check |
