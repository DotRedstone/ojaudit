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
