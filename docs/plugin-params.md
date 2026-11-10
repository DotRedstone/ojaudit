# 内置插件参数清单

内置插件的 `plugin.toml` 由 `ojaudit.core.plugins.discover_manifests` 发现；`params` 由 `validate_parameters` 验证。TUI 设置页（PR #14）读取 `type`、`label`、`default`、`min`、`max`、`choices` 自动生成控件。

## 检测插件

| 清单 | 参数 | 默认值 |
| --- | --- | --- |
| normalize | 无 | 无 |
| similarity | ngram_size, rare_threshold | 5, 3 |
| template | ngram_size, rare_threshold, crowd_threshold | 5, 3, 3 |
| timeline | 无 | 无 |
| classify | solid_l2, solid_delta_seconds | 0.98, 1800 |
| classify | mid_strong_rare, mid_strong_l3 | 0.5, 0.85 |
| classify | suspicious_l3, suspicious_rare, crowd_threshold | 0.8, 0.3, 3 |

`normalize`、`timeline` 的公开函数没有可配置参数，因此使用空 `[params]`，不为设置页制造无效控件。三个导出器 `csv`、`markdown`、`html` 也只接受行数据与输出路径，没有额外运行参数，均声明空 `[params]`。

所有数值默认值与 `similarity.py`、`template.py`、`nowcoder.py` 当前实现保持一致。此 PR **只增加元数据**，不会改变检测执行逻辑或导出结果。当前清单参数供设置页展示与验证，实际执行管线如何映射设置项仍由后续集成处理；不得据此假定修改 UI 参数已经影响检测运行。

## 约束

- `int` 不接受布尔值；`float` 允许整型数值但不接受布尔值。
- `min`、`max` 对数值参数生效。
- 未声明的参数将被拒绝。
- 本轮不修改 roadmap、CLI、TUI、flake.nix。
