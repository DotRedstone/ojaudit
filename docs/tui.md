# TUI（第 6 阶段实现）

入口为 `python -m ojaudit.tui.app`，不修改现有 CLI；待第 5 阶段入口合并后再对接默认命令。使用 Textual 的一层一屏 Screen 栈，所有数据只读自本地 SQLite，不访问 OJ，不写入数据库。

## 导航

```text
首页
└── 比赛列表（按本地正则黑白名单过滤；a 切换显示全部）
    └── 比赛总览（当前分析轮次的线索数、选手数、题目数、提交数）
        ├── 线索（第 7 阶段）
        ├── 选手（第 7 阶段）
        ├── 题目（第 7 阶段）
        └── 排行榜（第 8 阶段）
```

首页的打开比赛 ID、账户/登录、设置入口暂为提示，不触发业务操作。总览下级页面亦然。列表筛选直接复用 [核心筛选规则](data-model.md)，黑名单优先；切换全部模式会标注“规则外”，不修改配置。

## 按键与视觉

- `Enter` / `l`：进入当前项；`Esc` / `h`：返回上层。
- `j` / `k`：上下；`g` / `G`：首尾。
- `a`：在比赛列表切换筛选/全部；`?`：帮助提示；`q`：退出。
- 顶部显示面包屑；主窗格为圆角边框与边框标题，聚焦时边框高亮；底部状态栏显示模式、当前对象、任务状态（本阶段固定空闲）和主题标签。
- 语义颜色定义在 `src/ojaudit/tui/palette.py`。主题切换、任务进度订阅、审查语义高亮的业务接线留给后续阶段。

## 本地数据与验证

默认只读 `~/.local/share/ojaudit/ojaudit.db`（可通过 `XDG_DATA_HOME` 更改根目录）；数据库不存在时显示空列表，不创建库。可通过 `AuditApp(LocalContests(db_path, contest_filter))` 注入数据源用于测试。用户筛选规则从 `~/.config/ojaudit/config.toml` 加载；无规则时显示全部。

运行 `ruff check .`、`ruff format --check .`、`pytest -q`；`tests/tui/test_shell.py` 用合成 SQLite 数据与 `App.run_test()`/Pilot 测试导航和统计。

后续阶段与 PR 状态统一见 [roadmap](roadmap.md)。
