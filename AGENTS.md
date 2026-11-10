# Agent 执行约束

- 开始前检查 `git status --short`；保留用户未提交改动。
- 先阅读 `docs/repository-map.md`，再阅读对应模块权威文档。
- 不直推 main，不自动合并；每阶段以独立 Draft PR 交付。
- Conventional Commits：类型/作用域英文，描述中文；行为、重构、文档分开提交。
- 不提交 Cookie、UID、令牌、真实比赛、选手、代码或审查数据；测试仅用合成数据。
- 用户数据采用 XDG 目录，凭据权限 0600；危险操作需确认。
- 只有跨步骤交接/审查需要临时清单；阶段进度只维护在 [docs/roadmap.md](docs/roadmap.md)，合并对应 PR 时勾选。
- 跨 PR 遗留问题创建带作用域标签的 GitHub Issue，具体规则见 [docs/development-workflow.md](docs/development-workflow.md)。
- 代码注释 TODO/FIXME 必须符合开发流程文档格式并引用 Issue；FIXME 仅用于已知错误。
- PR 描述报告文件、行为变化、验证、风险/回退、迁移要求、新增 TODO。
- 每个 Python 模块须有 Module、Description、Scope 头部 docstring；高风险模块添加 Notes。
