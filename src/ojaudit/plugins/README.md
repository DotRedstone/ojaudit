# 插件目录

- `sources/`：数据源。内置牛客只读采集。
- `detectors/`：内置检测流水线 `engine.py`，阶段为 `fingerprint`、`similarity`（含 `tokens`）、`template`、`timeline`、`classify`；各阶段参数由同名子目录的 `plugin.toml` 声明。
- `exporters/`：Markdown / CSV / HTML 排行榜导出。

插件不得直接操作数据库，数据以标准对象交给核心层（`core.store`、`core.ingest`、`core.analysis`）。第三方插件只登记清单，不执行代码。说明见 `docs/plugin-api.md` 与 `docs/detection.md`。
