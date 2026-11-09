# 架构

框架负责标准数据格式、插件发现、配置、任务调度、人工复核和 TUI。数据源、检测器、导出器均通过插件提供。

数据流：采集 → 标准化存储 → 确定性分析 → 人工复核 → 排名与导出。

## 模块边界

- `core.schema`：平台无关数据对象与字段约束。
- `core.store`：SQLite 连接、schema 迁移与持久化。
- `core.config`：XDG 配置路径及 TOML 读写。
- `core.plugins`：插件清单校验和发现；不隐式执行第三方代码。
- `core.pipeline`：按明确顺序编排数据源和检测器。
- `plugins/`：内置或外部能力实现。
- `tui/`：Textual Screen 栈与交互界面。

模块权威接口见 [data-model.md](data-model.md) 与 [plugin-api.md](plugin-api.md)。阶段进度唯一来源为 [roadmap.md](roadmap.md)。
