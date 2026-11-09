# 检测算法与迁移边界

阶段 3 将 nowcoder-collect 的确定性规则迁入内置 detector。当前已迁移核心 pair 分析最小实现，入口为 `ojaudit.plugins.detectors.nowcoder.analyze`。

## 已迁移

- L1 原文、L2 去空白、L3 标识符 alpha-renaming 相似度。
- 基于不同 UID 计数的稀有 n-gram。
- 同题同语言分组、每人代表提交选择。
- AC 时间线、失败类型、方向有效性。
- 人群相同代码计数与确定性分级。

## 兼容与差异

- 输入使用核心 `Submission` 标准对象；不读取旧 SQLite 表，也不访问 Nowcoder 网络或凭据。
- 结果为排序稳定的 Python 字典列表；暂不提供旧版 JSON meta 包装和 CLI 命令。
- 迁移测试仅使用合成提交。真实比赛数据回归需在授权且本地隔离的数据环境运行，不纳入 CI。
- L3 当前保留内置关键字集合；后续可在独立 PR 扩充语言词表与边界测试。

## 第三阶段内置检测器

新增可独立组合的 pair、single、classifier：pair 使用 Winnowing 指纹与 Jaccard，single 输出代码规模与注释比例，classifier 将相似度映射为可配置的解释等级。三者均按稳定键排序，阈值显式配置，不联网。所有结果均为人工复核线索，不是违规认定。
