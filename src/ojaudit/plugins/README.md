# 插件目录

本目录包含内置与外部插件。数据源、检测器、导出器分别位于对应子目录。第三方插件导入会执行外部代码，默认停用；启用前必须展示并审查元信息，固定到明确版本或 commit。插件不得直接操作核心数据库，数据通过标准对象交给核心层。验证方式：运行 `pytest`。

内置插件已提供牛客只读 Source、pair/single/classifier 检测器及 Markdown/CSV 导出器。牛客 Cookie 通过环境变量提供（默认 `NOWCODER_COOKIE`），不要提交凭据或真实比赛数据。

## 内置算法映射

牛客旧检测器五个算法模块及清单一一对应：detectors/normalize.py、similarity.py、template.py、timeline.py、classify.py，分别位于 plugins/detectors/，各自的 plugin.toml 位于同名子目录。旧流水线的 preprocess.py 由核心标准对象和分组规则承担，不计入五个算法模块。

导出器：exporters/markdown.py、exporters/csv.py、exporters/html.py。HTML 报告对外部字段转义，并可展示分数、时间线和代码对照；不加载远程资源。
