# 架构

框架负责标准数据格式、插件发现、配置、任务调度、人工复核和 TUI。数据源、检测器、导出器均通过插件提供。

数据流：采集 → 标准化存储 → 比赛筛选 → 管理者过滤 → 确定性分析 → 人工复核与人员标记 → 排名与导出。

## 模块边界

- core.schema：平台无关数据对象与字段约束。
- core.store：SQLite 连接、schema 迁移与全部写入；写入经 `transaction()`，嵌套调用并入最外层事务，失败整体回滚。
- core.ingest：数据源包、JSON 导入包、旧 nowcoder-collect 库 → 标准对象 → 单事务写入。
- core.config：XDG 配置路径及 TOML 读写。
- core.filters：比赛正则白黑名单、规则外手动打开标记。
- core.people：全局隐藏人员名单与检测输入过滤。
- core.reviews：线索复核状态与失效提示。
- core.ranking：人员标记/隐藏名单策略与最终排名。
- core.plugins：插件清单校验和发现；不隐式执行第三方代码。
- core.analysis：一次比赛分析的完整流程（配置与参数校验、排除管理者、运行检测、写库），CLI 与 TUI 共用。
- plugins/：内置或外部能力实现。
- tui/：Textual Screen 栈与交互界面。

模块权威接口见 data-model.md 与 plugin-api.md。阶段进度唯一来源为 roadmap.md。
