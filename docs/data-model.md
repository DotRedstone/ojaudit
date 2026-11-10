# 标准数据格式

## 状态

本阶段定义 schema v1；数据库由核心层维护，插件只返回标准对象。

## 实体与主键

| 表 | 主键 | 主要字段 |
| --- | --- | --- |
| platforms | platform | 平台标识 |
| contests | platform, contest_id | name、start_time、end_time、raw_meta |
| problems | platform, contest_id, problem_index | problem_id、title、full_score |
| participants | platform, contest_id, uid | name |
| submissions | platform, contest_id, submission_id | uid、problem_index、language、verdict、score、submit_time、phase、code、raw_meta |
| analysis_runs | run_id | platform、contest_id、plugin_set、created_from、created_at |
| findings | run_id、双方 UID、problem_index、language | verdict_level、scores、reasons |
| single_signals | run_id、uid、problem_index、plugin、signal | value、reason |
| finding_reviews | run_id、双方 UID、problem_index、language | status、note、updated_at |
| person_marks | platform、contest_id、uid | mark、note、updated_at |

人工复核表与检测输出分离。重新分析写入新的 run，不覆盖旧 run 的人工记录。数据库通过 `schema_version` 管理迁移；程序发现数据库版本高于自身时拒绝降级打开。

## 标准化约束

- 所有比赛内实体使用 `platform + contest_id` 作为归属范围。
- 语言归一为 `cpp / python / java / other`。
- 提交阶段为 `before / contest / after`，时间戳统一使用毫秒。
- 原始平台字段放入 JSON 文本 `raw_meta`，不得替代标准字段。
- 样例和测试数据只能使用合成标识与代码。

## 当前实现边界

`core.schema` 提供 Contest、Problem、Participant、Submission 数据对象及提交记录校验；`core.store` 建立 schema v1 并提供比赛元数据写入。其余表结构已建立，完整 CRUD 与后续迁移将在后续阶段扩展。
