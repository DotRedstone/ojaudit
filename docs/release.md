# 发布流程（仅文档，不代表已经发布）

1. 完成所有待合并阶段 PR 的审查与测试；确认 `pytest -q`、`ruff check .`、`ruff format --check .`、`nix flake check`。
2. 确认 `pyproject.toml` 中版本与 CHANGELOG 的待发布版本一致，检查打包包含内置 `plugin.toml`。
3. 维护者审查版本号、CHANGELOG、源码及依赖；合并完成后再由有权限的维护者决定是否创建符合 `vX.Y.Z` 的 tag。
4. `.github/workflows/release.yml` 仅由 tag 推送触发，先校验再构建 wheel/sdist，并将构建产物上传到 Actions。**当前不自动发布到 PyPI 或创建 GitHub Release。**
5. 在正式发版前验证 `nix run github:DotRedstone/ojaudit` 与 `pipx install .`、`uv tool install .`。

## 当前限制

- 此 PR 不创建 tag、不发版、不修改 main。
- 真实牛客接口、历史迁移格式和第三方插件联网行为仍分别由 Issue #8、#9、#10 跟踪。
- 榜单是本地成绩推导，不是官方榜单；检测输出仅供人工复核。
