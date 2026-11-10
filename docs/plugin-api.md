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

`core.plugins` 实现了 plugin.toml 解析、API 版本校验、目录清单发现、entry point 元信息发现和参数默认值/类型/范围校验。`ojaudit plugins install` 只登记第三方插件的清单，**不会加载或执行第三方代码**；目前没有第三方插件的执行入口。

内置能力：

- Source：`plugins.sources.nowcoder.NowcoderSource`，只读采集；Cookie 来自本机 0600 文件或配置指定的环境变量，不写入标准对象、数据库或日志。默认只采比赛期间数据，`phase` 可选 `contest`、`after`、`all`。
- 检测：`plugins.detectors.engine`，由指纹、相似度、模板、时间线、分级五个阶段组成，每个阶段一个 `plugin.toml` 声明参数，由 `core.analysis` 校验后传入。详见 [检测](detection.md)。
- Exporter：`plugins.exporters` 下的 Markdown / CSV / HTML，输出排序稳定；CSV 对公式前缀转义，HTML 对外部字段转义且不加载远程资源。

检测与导出阶段不联网；牛客 Source 是唯一需要网络的阶段。
