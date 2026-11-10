# TUI（第 6—9 阶段实现）

入口为 `ojaudit`（无子命令）或 `python -m ojaudit.tui.app`。使用 Textual 的一层一屏 Screen 栈，采集与检测数据只读自本地 SQLite，不访问 OJ。人工线索复核和人员标记仅通过核心 Store 写入专用表，不会覆盖分析结果。

## 导航

```text
首页
└── 比赛列表（按本地正则黑白名单过滤；a 切换显示全部）
    └── 比赛总览（当前分析轮次的线索数、选手数、题目数、提交数）
        ├── 线索 → 证据（插件分数、理由/时间线、左右代码与 diff）
        ├── 选手 → 选手详情 → 题目 → 提交历史 → 代码
        ├── 题目 → 所有人的代表代码 → 代码
        └── 排行榜（本地派生预览、人员策略、md/csv/html 导出）
```

首页「打开比赛 ID」通过本地库查找并直达总览，找不到时提示先执行 `ojaudit collect <ID>`；不会自动联网采集。「账户 / 登录」使用隐藏输入框接收 Cookie，通过 CLI 共享的 `save_cookie` 写入权限 0600 的本地文件；不会在 UI 显示 Cookie。首页「设置」和总览「排行榜」均已接入。列表筛选直接复用 [核心筛选规则](data-model.md)，黑名单优先；切换全部模式会标注“规则外”，不修改配置。

## 键盘、鼠标与视觉

界面启动后焦点直接在首页主列表，无须先按 Tab。文本输入框允许正常输入字母与空格，Esc 用于退出弹窗。

| 意图 | 新手键盘 | Vim | 鼠标 |
|---|---|---|---|
| 上下移动 | ↑ / ↓ | j / k | 滚轮、单击一项只选中 |
| 进入列表项 | → / Enter / Space | l | 双击列表项 |
| 返回 | ← / Esc | h / q（子页面） | 单击面包屑返回上一级 |
| 首项 / 末项 | — | g / G（Shift+g） | 滚轮 |
| 搜索列表 | / | / | 输入搜索文字后按查找 |
| 全局帮助 / 主题 | ? / t | ? / t | Footer 中可见的操作 |
| 退出程序 | 首页 q | 首页 q | — |

所有支持的页面显示 Textual Footer（可点击的操作提示）和状态栏；状态栏展示当前页面与主题。可点击的列表与面包屑有 hover 提示，列表高亮使用真正的 `ListItem.-highlight` 样式。

证据页：`↑/↓` 或 `j/k`、`n/p` 浏览线索，`Tab` 切换代码对照/diff，`r` 人工复核，`m` 人员打标，`u` 切换目标人员；`g/G` 到首/末线索。代码页：`n/p`、`↑/↓`、`j/k` 前后浏览当前集合，`[`/`]` 切换同人同题历史，`m` 打标；左键、Esc、h 返回。

设置页：`Tab` / `Shift+Tab` 切换分类/选项栏；`↑↓` / `j/k` 移动当前栏；在分类栏 `→/l/Enter` 进入选项栏，在选项栏按 `→/l/Enter` 编辑当前项，`Space` 切换布尔/循环枚举；`←/h` 返回分类栏，再次返回上一页。保留 `Ctrl+S` 保存、`r` 恢复本类默认。

排行榜：`↑↓` / `j/k` 选择行，`Tab` 切换策略/预览；在策略栏按 `→/l/Enter/Space` 循环当前策略、`Shift+←` 回到前一选项；`←/h/Esc` 返回，`e` 导出。预览列表只读。

输入弹窗：`Esc` 取消（即使焦点在 Input 内），输入框 `Enter` 确认；按钮仍可用鼠标点击。`ChoiceDialog` 下拉列表打开时先按 Esc 收起下拉，再按 Esc 取消整个对话框。设置未保存确认默认聚焦「继续编辑」，按 Enter 不会误丢弃修改。

空库首页提示 `ojaudit login → ojaudit collect <比赛ID> → ojaudit analyze <比赛ID> → ojaudit`，比赛列表在没有记录时也提示下一步命令；所有菜单仍可操作。

## 本地数据与验证

默认只读 `~/.local/share/ojaudit/ojaudit.sqlite`（可通过 `XDG_DATA_HOME` 更改根目录）；数据库不存在时显示空列表，不创建库。可通过 `AuditApp(LocalContests(db_path, contest_filter))` 注入数据源用于测试。用户筛选规则从 `~/.config/ojaudit/config.toml` 加载；无规则时显示全部。

运行 `ruff check .`、`ruff format --check .`、`pytest -q`；`tests/tui/test_shell.py` 和 `tests/tui/test_review.py` 用合成 SQLite 数据与 `App.run_test()`/Pilot 测试导航、复核、标记同步和代码跳转。

## 数据与接口边界

- `review_data.py` 仅执行绑定参数的本地查询；人员标记和线索复核调用 `Store.put_person_mark` / `Store.put_finding_review`，不直接写业务表。
- 代表代码按最高分、同分最长代码、再按提交时间与 ID 排序选出；历史提交包含非 AC 状态。
- 当前分析以最新 `analysis_runs.created_at` 为准，旧复核的线索键若不在当前结果中则标记“已失效”。旧分析的复核状态不会自动归到新 run。
- 证据评分和理由直接显示分析结果 `scores` / `reasons` 的 JSON 数据；若没有单独的时间线详情，则不会凭空生成。
- 新的详细证据时间线结构、历史失效线索的独立持久化索引与更精细的权限接口仍依赖核心层后续扩展，本阶段只做已有字段可支持的展示。

后续阶段与 PR 状态统一见 [roadmap](roadmap.md)。

## 第 8 阶段：设置

设置页按账户、比赛筛选、人员名单、采集、检测、插件管理、外观、快捷键、关于分类。左侧分类、右侧选项；`Tab` 切换窗格，`Space` 切换布尔值，`h/l` 调整数值或枚举，`Enter` 编辑文本/数值，`r` 恢复本类默认值，`Ctrl+S` 保存。改动项前有 `●`，选项说明展示默认值；未保存离开会弹出确认。

配置读写复用 `core.config.load_config` / `save_config`，保留无关 TOML 键；不在配置中保存 Cookie 或 Token，账户类只填写环境变量的名称。插件发现复用 `discover_manifests`；检测插件参数按照清单的 bool/enum/int/float/str 与 min/max/schema 创建控件，并使用 `validate_parameters` 检查。插件安装入口只显示说明，不联网，也不执行插件入口点。比赛正则设置映射回核心所需的 whitelist/blacklist 规则数组，保留同组其他规则；人员名单按平台读取本地 hidden_people，通过核心 Store 方法增删，保存前不写库。

注意：内置检测插件的当前内置检测插件已声明参数，可在设置页自动生成；插件启用状态目前仅写入设置，**不代表后端已经执行插件**。采集参数、默认检测总开关、界面紧凑模式等现阶段仅存储配置，尚无完整后端消费接口；部分设置需后续核心契约验收。

## 第 8 阶段：排行榜

排行榜支持作弊者「剔除/标记」、存疑者「照常/标记/剔除」、管理者「剔除/标记」，以及 md/csv/html 选择；`h/l` 切换当前策略，`e` 导出。预览由核心 `build_final_ranking()` 计算；待复核线索与未标记人员会产生提醒但不阻止导出。

**当前缺少官方排行榜快照**：数据库没有官方名次及罚时字段，因此临时按照本地每人每题最高提交分数排序，并明确标识「非官方推导」；此结果不能作为正式官方成绩。CLI/TUI 现均将排行榜行交给导出插件，并有 CSV 字节一致性回归测试。生成文件保存在 `$XDG_DATA_HOME/ojaudit/exports/<platform>/<contest_id>/ranking.{md,csv,html}`，无 XDG 环境变量时使用 `~/.local/share`；平台和比赛 ID 经过路径段验证。

本阶段新增合成数据测试 `tests/tui/test_settings_ranking.py`；阶段/PR 的唯一进度来源仍为 [roadmap](roadmap.md)。

## r19 批次 B：数据库路径

数据库路径的优先级为：命令行 `--db PATH` > 配置文件 `[storage] sqlite_path = "..."` > `$XDG_DATA_HOME/ojaudit/ojaudit.sqlite`（未设置 XDG 变量时为 `~/.local/share/ojaudit/ojaudit.sqlite`）。

不带子命令启动 `ojaudit --db PATH` 时，TUI 会打开同一 SQLite 数据库，设置中的管理者名单也对应当前数据库。可在「账户 → SQLite 路径」保存下次启动使用的数据库位置；本次启动若指定了 `--db`，始终以命令行选项为准。数据库不存在时，可先 `ojaudit login`，再 `ojaudit collect 比赛ID`。

## 壁纸主题与视觉风格（r18）

默认主题为 `auto`，优先读取 `OJAUDIT_THEME_FILE` 指定的本地 JSON；未指定时依次查找 `~/.cache/wal/colors.json`、`~/.cache/matugen/colors.json`、`~/.config/matugen/colors.json`。支持 pywal 的 special/colors 和常见 matugen dark/default/color JSON。只读取经过十六进制校验的颜色，不执行 pywal/matugen 命令，不注入 JSON 内的 CSS；无效、过大（超过 256 KiB）和不可读文件自动忽略。

外观主题可选 `auto`、`wallpaper`、`ansi-dark`、`catppuccin-mocha`、`nord`、`gruvbox`、`textual-dark`。无有效壁纸文件时回退深色内置主题；当选择 auto/wallpaper 时每四秒检查本地壁纸配色文件变化。旧配置中的 ansi/catppuccin 仍可读取。外观设置保留 Nerd Font 开关，并增加按键提示开关，默认紧凑列表。

风格集中在 `src/ojaudit/tui/themes/nowcoder.tcss`：深色背景、单行面包屑、圆角框（聚焦变强调色）、半透明选中、淡色状态栏；状态栏左侧是 NORMAL 胶囊，中间是比赛与当前层，右侧是主题与本地时间。关闭 Nerd Font 时使用普通 `▌` 分隔符。一层一屏导航与现有按键行为未变，本分支不修复键位或数据功能。

对照来源：`DotRedstone/nowcoder-collect` 的 `feat/hierarchical-review-workflow`，`rice_theme.py` 与 `review_tui.py` 的 Page/ReviewApp CSS。视觉截图冒烟与 JSON 校验见 `tests/tui/test_style.py`；SVG 均生成在测试临时目录，不提交用户数据。
