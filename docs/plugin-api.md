# 插件接口（API v1）

## 安全模型

插件发现与插件执行严格分离。发现清单或 entry point 元信息不会导入插件模块。第三方插件默认禁用；启用前必须展示名称、类型、版本、API 版本、来源和参数声明，并固定到明确版本或 commit。插件不得直接操作 SQLite，不得在检测/导出阶段自行访问网络。

## 清单

每个插件目录包含 `plugin.toml`：

```toml
name = "rare_ngram"
kind = "detector.pair"
version = "1.0.0"
api_version = 1
description = "稀有 n-gram 指纹相似度"
languages = ["cpp", "python", "java"]

[params.k]
type = "int"
default = 5
min = 3
max = 12
label = "n-gram 窗口"
```

允许类型：`source`、`detector.pair`、`detector.single`、`detector.classifier`、`exporter`。参数支持 int、float、bool、str、enum；数值参数可声明 min/max。

## 接口约定

- Source：声明认证方式、列出已加入比赛、采集比赛数据、可选获取官方榜单、归一语言。插件返回标准数据对象，由核心写库。
- Pair detector：对同题同语言的两份代表代码比较，返回分数与理由；需要组级统计时先 prepare。
- Single detector：检查单人历史，返回独立信号及理由。
- Classifier：结合 pair 分数、时间线与上下文输出等级和理由。
- Exporter：接收核心计算好的最终榜单和选项，输出文件路径。

检测与导出必须确定性：禁止随机数、墙钟时间和网络访问；浮点结果统一 round 到 4 位；输出必须带可读理由。

## 当前实现

`core.plugins` 已实现 plugin.toml 解析、API 版本校验、目录清单发现、entry point 元信息发现和参数默认值/类型/范围校验。实际插件执行入口将在后续阶段实现，不能把“发现”视为“已启用”。
