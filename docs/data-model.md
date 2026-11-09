# 标准数据格式（草案）

计划使用带 schema_version 的 SQLite。核心实体：platforms、contests、problems、participants、submissions、analysis_runs、findings、single_signals、finding_reviews、person_marks。所有跨平台实体主键含 platform；人工记录与检测结果分开，重新分析不得覆盖人工记录。完整字段与迁移规则在第二阶段定稿。
