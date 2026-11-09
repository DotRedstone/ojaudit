# CLI 与旧 JSON 数据迁移

阶段 5 的 CLI 使用本地 SQLite，默认路径为 XDG_DATA_HOME/ojaudit/ojaudit.sqlite，可用全局 `--db` 指定路径。所有命令都支持 `--help`。

```bash
ojaudit --db /tmp/synthetic.sqlite migrate synthetic.json
ojaudit --db /tmp/synthetic.sqlite contests
ojaudit --db /tmp/synthetic.sqlite hidden add --platform synthetic --uid staff
ojaudit --db /tmp/synthetic.sqlite analyze synthetic c1
ojaudit --db /tmp/synthetic.sqlite mark synthetic c1 u2 suspect --note "待核查"
ojaudit --db /tmp/synthetic.sqlite export synthetic c1 --output /tmp/ranking.csv
```

`review` 命令需要分析输出的 run_id、双方 UID、题目序号、语言和状态。

`migrate` 接收 JSON 对象，包含 `contest`（platform、contest_id、name）、`participants`（uid、name）和 `submissions`（submission_id、uid、problem_index、language、verdict、score、submit_time、phase、code）数组。重复导入按主键更新，不删除人工记录。当前仅支持此 JSON 格式，不对任意旧版 SQLite 数据库作兼容承诺。

`export` 支持 `--cheaters drop|mark`、`--suspects keep|mark|drop`、`--managers drop|mark`。导出的是按本地提交最高分和 UID 排序的合成榜单；并非牛客官方排名，不适合作为官方名次使用。CSV 对公式前缀转义。

比赛筛选读取用户 `config.toml` 中的 `contest_filter`；隐藏管理者名单全局按 platform + uid 存储，检测分组前剔除。

CLI 默认不联网、不读取 Cookie，不操作 TUI。

## 第 10 轮补充命令

```bash
ojaudit migrate --from-nowcoder-collect --db ~/.dsh/nowcoder/nowcoder.db --reviews reviews.json
ojaudit contests --all
ojaudit login --platform nowcoder
ojaudit collect 123456
ojaudit analyze 123456 --json-out report.json
ojaudit rank 123456 --cheaters drop --format md --output ranking.md
ojaudit rank 123456 --format csv --output ranking.csv
ojaudit rank 123456 --format html --output ranking.html
ojaudit plugins list
ojaudit plugins install /path/to/local-git-repo@<commit-sha>
ojaudit plugins enable plugin-name
ojaudit plugins disable plugin-name
```

- `migrate --from-nowcoder-collect` 从旧版 SQLite 的 contests/submissions 表只读导入；原数据库不修改、不删除。可选 `--reviews` 接收显式数组格式的复核 JSON（run_id、uid_a、uid_b、problem_index、language、status、updated_at，note 可选）；不支持未知 reviews.json 格式时会报错。
- `login` 交互式读取 Cookie，保存至 XDG 配置目录 `nowcoder.cookie`，权限 0600，不在命令行传入。采集仅通过现有 NowcoderSource 的只读接口；测试不联网。
- `plugins install` 当前只做 git commit 固定版本检出、plugin.toml 校验及登记，默认禁用。enable/disable 只更新登记状态，**不执行第三方插件**。
- `rank` 通过现有 md/csv/html 导出插件。旧 `export` 保留为兼容入口。
- 无子命令时尝试调用 `ojaudit.tui.app.main`，如 TUI 尚未就绪则给出提示，不在本阶段修改 TUI 实现。
