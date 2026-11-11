# 检测

检测只产生**人工复核线索**，不构成违规认定。所有阶段确定性、不联网：同一数据库多次分析结果逐字节一致。

## 流程

入口为 `ojaudit.core.analysis.run_analysis()`（CLI `ojaudit analyze` 与 TUI 共用），检测本身在 `ojaudit.plugins.detectors.engine.analyze()`：

1. 读取比赛提交，排除全局管理者名单中的人员。
2. 按「题目 + 语言」分组（C 与 C++ 同组）；每人取一份代表提交：最高分 → 最长代码 → 最早提交。
3. **找候选对**：只有「共享至少一个稀有片段」或「去空白后完全相同」的选手对才可能成为线索（分级规则要求不完全相同的线索必须共享稀有片段）。稀有片段按定义最多被 `rare_threshold` 人使用，用倒排索引直接取出这些选手对，不做两两比较。若把 `mid_strong_rare` 或 `suspicious_rare` 设为 0，规则不再要求共享片段，退回全部两两比对。
   - 同时计算原文 Winnowing 指纹（`fingerprint.py`）的 Jaccard 相似度，作为参考指标写入线索；`threshold` 默认 0（不过滤），设为正数时作为额外条件。
   - 以前这一步用原文指纹相似度 ≥ 0.5 做初筛。变量整体改名会大幅拉低原文指纹相似度，改名抄袭在初筛就被放过：一场 43 人的真实比赛上，旧初筛只给出 8 条线索，全部比对应有 18 条，漏掉的里面有一对词法归一后相似度 0.99。
4. 对候选对做精细比对：
   - `similarity.py`：L1 原文、L2 去空白、L3 词法归一（`tokens.py`：标识符按首次出现重命名，数字/字符串归一）三种 `difflib` 相似度；去空白后是否完全一致；稀有 n-gram（最多被 `rare_threshold` 人使用的片段）共享度。
   - `template.py`：去空白后与多少人完全相同（同码人数）。
   - `timeline.py`：谁先通过、通过时间差、后者首次提交是否在前者通过之后（方向有效）、后者通过前的失败次数与类型。
5. `classify.py` 按规则表分级；「排除」不写入数据库。

三处加速都只省计算、不改变结果：第 3 步的倒排索引找候选；第 4 步中若仅凭稀有片段与时间线即可确定为「排除」（不完全相同、无足够稀有片段、时间线不满足实锤条件）就跳过逐字比对；以及相似度的快速上界（difflib `quick_ratio`，必然不低于真实值）达不到任何一条规则门槛时跳过逐字比对。`tests/plugins/test_detectors.py` 有与全部两两比对的等价性测试（多组随机样本）、改名抄袭不被漏掉的测试和跳过条件的随机化测试。43 人真实比赛约 0.4 秒；按真实代码合成的 1200 人 × 8 题约 8 秒。

## 分级规则

| 条件（按顺序） | 等级 |
| --- | --- |
| 去空白后完全一致，且同码人数 ≥ `crowd_threshold` | 排除（公共模板） |
| 完全一致，或 L2 ≥ `solid_l2` **且至少共享一个稀有片段**；并且方向有效、通过时间差 < `solid_delta_seconds` | 实锤 |
| 完全一致（时间线不满足上一条） | 中偏强 |
| 稀有片段共享度 ≥ `mid_strong_rare` 且 L3 ≥ `mid_strong_l3` | 中偏强 |
| L3 ≥ `suspicious_l3` 且稀有片段共享度 ≥ `suspicious_rare` | 存疑 |
| 其他 | 排除 |

与旧 nowcoder-collect 规则相比只有一处不同：L2 达标但不完全相同的选手对，必须至少共享一个稀有片段才能定为实锤。在一场 1136 人的真实比赛上，旧规则给出 595 条实锤，其中 563 条出自一道代码中位长度 180 字符的简单题，且双方没有任何稀有片段（每个片段都被 3 人以上使用），属于常见写法；新规则下实锤为 39 条，难题上的线索基本不变。完全相同的代码仍按旧规则处理，因此难题上的抄袭团伙不会被这条规则隐藏。

旧版的其余合成向量保留在测试中。

## 参数

参数在「设置 → 检测」中编辑，保存在配置 `[plugins.<名称>]`；由各阶段的 `plugin.toml` 声明类型与范围，并在分析时校验。配置里已废弃的参数键会被忽略。优先级：`ojaudit analyze --threshold` > 配置 > 默认值。

| 阶段 | 配置名 | 参数 | 默认值 |
| --- | --- | --- | --- |
| 指纹 | `builtin_pair` | `threshold`（额外下限）, `k`, `window` | 0, 5, 4 |
| 相似度 | `nowcoder_similarity` | `ngram_size`, `rare_threshold` | 5, 3 |
| 分级 | `nowcoder_classify` | `solid_l2`, `solid_delta_seconds` | 0.98, 1800 |
| | | `mid_strong_rare`, `mid_strong_l3` | 0.5, 0.85 |
| | | `suspicious_l3`, `suspicious_rare`, `crowd_threshold` | 0.8, 0.3, 3 |
| 模板 | `nowcoder_template` | 无（只能开关） | — |
| 时间线 | `nowcoder_timeline` | 无（只能开关） | — |

前三个阶段必需，设置页中不可关闭，配置里的 `enabled = false` 对它们无效；模板与时间线可关闭：关闭模板后同码人数不参与排除，关闭时间线后不会出现「实锤」。

## 写入的数据

每次分析新建一条 `analysis_runs`，线索写入 `findings`：`verdict_level` 为分级，`scores` 含 `similarity`、`L1`、`L2`、`L3`、`md5_ws_equal`、`rare_score`、`template_crowd`、`timeline`，`reasons` 为可读理由列表。人工复核按线索键（双方 UID、题号、语言）跨轮次沿用，见 [数据模型](data-model.md)。
