# ojaudit

面向训练赛管理者的本地代码审查工具。支持牛客只读采集、确定性相似度线索、人工复核、排名导出与 Textual TUI。**检测线索不等于违规认定。**

## 安装

- Nix：`nix run github:DotRedstone/ojaudit`（需在对应版本公开且 flake 输出可用时）
- pipx：`pipx install .`
- uv：`uv tool install .`
- 开发：`python -m pip install -e '.[dev]'`

## 快速开始

1. `ojaudit login`：在交互提示中输入自己的牛客 Cookie（不传入命令行）。
2. `ojaudit contests --all`：查看已保存的比赛；首次使用时可能为空。
3. `ojaudit collect <contest_id>`：只读采集授权访问的比赛。
4. `ojaudit analyze <contest_id>`：生成本地检测线索。
5. `ojaudit`：进入 TUI，逐条复核线索、查看代码与管理选手。
6. `ojaudit rank <contest_id> --format csv --cheaters mark`：导出本地推导榜单（**非官方排名**）。

`ojaudit --help` 查看全部命令；旧数据迁移及插件管理见 [CLI 文档](docs/cli.md)。

## 文档

[架构](docs/architecture.md) · [TUI](docs/tui.md) · [检测](docs/detection.md) · [维护](docs/maintenance.md) · [发布流程](docs/release.md) · [路线图](docs/roadmap.md)。

配置位于 `$XDG_CONFIG_HOME/ojaudit`，数据库位于 `$XDG_DATA_HOME/ojaudit/ojaudit.sqlite`（默认采用各自 XDG 标准路径）。勿提交真实 Cookie、UID、比赛提交或人工审查数据。
