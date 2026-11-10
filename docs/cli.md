# CLI

数据库默认位于 `$XDG_DATA_HOME/ojaudit/ojaudit.sqlite`；优先级为全局 `--db PATH` > 配置 `[storage] sqlite_path` > 默认路径。所有命令支持 `--help`。不带子命令运行 `ojaudit` 进入 TUI。

## 典型流程

```bash
ojaudit login --qr                 # 微信扫码登录（或在 TUI 的「账户与登录」里扫码）
ojaudit collect 123456             # 只读采集（唯一联网的命令）
ojaudit analyze 123456             # 本地检测，生成线索
ojaudit                            # 在 TUI 中复核线索、标记选手
ojaudit rank 123456                # 导出 Excel 榜单（非官方；--cheaters drop 除名作弊者）
```

## 命令

| 命令 | 说明 |
| --- | --- |
| `login [--qr]` | `--qr` 在终端显示二维码，用微信扫码登录并自动识别 UID；不带参数时交互粘贴 Cookie（不经命令行参数）。保存到 `$XDG_CONFIG_HOME/ojaudit/nowcoder.cookie`，权限 0600。 |
| `collect <比赛ID>` | 用牛客数据源只读采集并在一个事务中入库；读取设置中的 `collect.*`（并发线程、速率上限、超时、重试、增量采集），开启 `collect.auto_analyze` 时随后自动分析。重新采集时默认只下载本地没有的源码。 |
| `contests [--all]` | 列出本地比赛；默认应用比赛筛选规则，`--all` 显示全部。 |
| `analyze <比赛ID> [--platform P] [--threshold T] [--json-out F]` | 运行检测并写入新一轮分析。`--threshold` 为指纹相似度阈值，优先于设置。参数说明见 [检测](detection.md)。 |
| `mark <平台> <比赛> <UID> normal\|suspect\|cheater [--note]` | 人工标记选手。 |
| `review <run_id> <UID_A> <UID_B> <题号> <语言> <状态> [--note]` | 复核一条线索，状态为 已核查 / 无需跟进 / 需进一步核实。 |
| `hidden add\|remove\|list [--platform --uid --nickname]` | 全局管理者名单；检测前剔除，排行榜按策略处理。 |
| `rank <比赛ID> [--platform P] [--format xlsx\|md\|csv\|html] [--output F]` | 导出最终排名，默认 Excel（中文表头、作弊者整行标红）。策略 `--cheaters drop\|mark`、`--suspects keep\|mark\|drop`、`--managers drop\|mark`、`--inactive keep\|drop`（剔除一次都未提交的人）。默认写到 `$XDG_DATA_HOME/ojaudit/exports/<平台>/<比赛>/ranking.<格式>`，与 TUI 相同。 |
| `export <平台> <比赛> [--output F] [--format]` | `rank` 的旧形式，保留兼容。 |
| `migrate <file.json>` | 导入 JSON 包：`contest`（platform、contest_id、name）、`participants`（uid、name）、`submissions`（submission_id、uid、problem_index、language、verdict、score、submit_time、phase、code，可选 problem_title）。 |
| `migrate --from-nowcoder-collect [--db 旧库] [--reviews F]` | 只读导入旧 nowcoder-collect SQLite（默认 `~/.dsh/nowcoder/nowcoder.db`），不修改原库；未知结构直接报错。`--reviews` 接收复核记录数组（run_id、uid_a、uid_b、problem_index、language、status、updated_at，note 可选）；记录不含比赛 ID，按双方 UID、题号、语言在旧库提交中定位比赛，无法唯一确定的逐条列在标准错误输出中，不导入。导入的复核在 TUI 中先显示为历史记录，重新分析出同一线索后自动沿用。 |
| `plugins list\|install\|enable\|disable` | 第三方插件登记。`install <地址>@<commit>` 只检出固定 commit 并校验 `plugin.toml`，**不执行插件代码**；安全约束见 [插件接口](plugin-api.md)。 |

## 说明

- 榜单按每人每题赛中最高分推算，赛前与赛后补题提交不计分；数据库没有官方名次与罚时，结果始终标注非官方。CSV 对公式前缀转义。
- 重复导入按主键更新，不删除人工记录；导入或迁移中途失败会整体回滚。
- 题号可为数字或字母（A=0、Z=25、AA=26）；语言归入 cpp / python / java / other。
