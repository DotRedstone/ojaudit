# ojaudit

面向训练赛管理者的平台无关代码审查框架（建设中）。

当前仅提供第一阶段仓库骨架，尚不支持真实比赛采集、检测或导出。

## 开发

Python 3.11+：`python -m pip install -e '.[dev]'`，运行 `pytest`、`ruff check .`。

规划与进度：[docs/roadmap.md](docs/roadmap.md)。架构与维护文档见 [docs/](docs/)。

## 入口

`ojaudit --help`；TUI 与其他子命令将在后续阶段实现。
