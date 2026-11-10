# 插件接口（草案）

计划支持 source、detector.pair、detector.single、detector.classifier、exporter，均有 plugin.toml 与 api_version。外部插件默认禁用，启用前审查元信息并固定版本。检测与导出必须确定性且提供人类可读理由。接口签名和参数校验在第二阶段定稿。
