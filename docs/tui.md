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

## Nerd Font 图标

在「设置 → 外观 → 使用 Nerd Font 图标」中切换并按 Ctrl+S 保存。开启后首页、比赛导航、证据与代码、人员标记、排行榜、设置及模态框的标题、列表、面包屑和状态栏使用 Nerd Font 私有区图标；需终端安装并选用兼容 Nerd Font 的字体。关闭后统一回退到文字标签，不输出 U+E000–U+F8FF 的图标字符，避免缺字方框。

图标码位只在 `src/ojaudit/tui/icons.py` 定义；界面调用 `label()` / `breadcrumb()`，不得在各屏硬编码私有区字符。设置保存后当前 App 的图标模式立即更新；已打开的其他界面重新进入时按当前模式渲染。Pilot 测试 `tests/tui/test_nerd_font_icons.py` 使用合成数据库验证开关两态及关闭时截图无私有区字符。

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


## r19 批次 D：采集、分析和待复核

- 首页新增「待复核」与「采集比赛 ID」；待复核跨本地比赛列出当前轮次的未处理线索和已标记为存疑的选手，可进入证据和人员详情。
- 比赛列表提供采集、分析所选比赛和取消任务的可见按钮；比赛总览提供「采集并检测」与「本地分析」。打开尚未采集的比赛 ID 时保留一层一屏的手工采集引导，而非只弹通知。
- 采集、入库和分析复用 Source、`import_bundle` 与 CLI 的 `_analyze`，由后台线程执行同步 I/O，不阻塞 TUI 浏览；当前步骤写入独立 SQLite 连接。底栏显示当前阶段和完成/失败状态。
- 「取消」会请求在安全的步骤边界停止；正在进行的网络请求或数据库事务不会被强制终止，可能完成当前步骤才停止。UI 不回显 Cookie 或异常详情，CI 仅使用合成数据和假 Source，不访问牛客。
- 为避免与键位 PR #18 冲突，本批只新增可见按钮、菜单项和数据逻辑，不修改原有 BINDINGS、弹窗按键或视觉主题。

## 批次 E：设置与规则列表

比赛筛选和人员名单设置页保留原有 `↑↓/j/k`、`Enter`、`Space`、`Ctrl+S` 等导航操作。选中列表项后，按 `a` 在比赛筛选新增白名单规则（在人员名单则新增管理者），按 `b` 新增黑名单规则，按 `d` 删除当前规则/管理者；`Enter` 编辑正则、UID 和姓名，`Space` 切换启用开关，`Ctrl+S` 保存。规则按顺序保留多条，黑名单优先，白名单为空时放行；删除或禁用规则不会误删同组其它条目。

管理者按平台保存在 `hidden_people`。勾选启用时由采集/检测与排行策略排除，取消启用时从 `hidden_people` 移除；未启用条目及姓名保留在配置文件 `[people]` 的 `manager_entries` 中供以后重新启用。旧版逗号分隔的 UID 字段仍兼容；切换平台应单独保存后再编辑名单。全部示例使用合成数据。

采集配置项 `collect.phase`、`collect.threads`、`collect.include_after`、`collect.auto_analyze`、`collect.retry_count`、`collect.readonly` 会被 CLI `collect` 读取。线程数限定为 1–16，重试次数为 0–10；只允许 GET 只读采集，若配置为非只读则显式拒绝；开启自动分析后在导入完成时启动本地分析。对于不存在的平台或比赛，`rank`/`export` 会直接报错，不会生成空排行榜文件。


## 批次 F：账户与列表体验

首页「账户 / 登录」进入独立一层一屏账户页面，提供四项：终端扫码登录、设置牛客 UID、粘贴 Cookie（备选）和退出登录。扫码沿用旧项目的牛客微信二维码票据与轮询流程，二维码由本地 `qrcode` 库生成，不请求第三方二维码服务；Textual 使用 `App.suspend()` 暂停绘制，仅在当前本机终端显示二维码。TUI 屏幕、截图、日志和通知不展示票据或 Cookie。扫码结果仍经现有 `save_cookie()` 写入权限 `0600` 的配置目录文件。扫码接口可能随牛客网站变化；CI 使用合成票据、无真实扫码测试。Web 模式等不支持终端暂停的环境需要改用「粘贴 Cookie」选项。

牛客 UID 仅接受十进制数字，保存在配置的 `[nowcoder].uid`，供现有数据源 `list_recent` 使用。退出登录只删除 ojaudit 本机保存的 Cookie，不会删除浏览器登录、环境变量或其它软件的凭据。若配置有外部 Cookie 环境变量，退出本机 Cookie 不等于注销外部凭据。

线索列表按 `f` 循环「全部 → 高优先级 → 未处理 → 已处理」，保留现有方向键、`hjkl`、鼠标、`Enter`、`Esc` 与 `/` 搜索，不另行抢占命令 `:`。高优先级只统计当前分析轮次的 `high`；全部视图仍显示历史已失效线索，三个过滤视图排除历史失效记录。

比赛列表补充日期（本地库未记录则「日期未知」）、提交数、采集/分析状态、当前线索 H/M/L 计数和已复核/总线索进度。状态依赖本地导入提交及最新分析运行，不冒充远程同步状态。排行榜当前没有可验证的官方 submit-list 快照，依旧只按本地提交分数推算，明确标记「非官方排名」，不将推导数据误称官方名次。

以上仅为批次 F 的交互与数据读取接线，不改既有壁纸主题、既有导航按键或检测算法；使用合成测试，无真实 Cookie、UID、比赛数据。
