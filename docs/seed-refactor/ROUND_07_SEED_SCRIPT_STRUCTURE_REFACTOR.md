# Round 7 Seed Script 删除式结构重构

## 本轮完成

- 删除 root `scripts/seed_*.py` 入口和旧样例链，外部 seed 命令统一为 `python -m scripts.seeds.cli --profile production|demo|local-demo|test`。
- 将生产导入代码迁移到 `scripts/seeds/loaders/`，demo 链路迁移到 `scripts/seeds/demo/`，测试夹具迁移到 `scripts/seeds/test/`，清洗工具迁移到 `scripts/seeds/curation/`，验收脚本迁移到 `scripts/seeds/validation/`。
- 删除旧样例数据源和旧样例脚本：`seed_foundation_samples.py`、`seed_vessel_samples.py`、`seed_freight_samples.py`、`seed_route_samples.py`、`seed_analysis_samples.py`、`seed_audit_samples.py`、旧 `scripts/seed_data/vessel/vessels.json`。
- 将航道大 Python 数据文件转为 `scripts/seed_data/navigation/navigation_channels.json`，生产航道 loader 改为只读 JSON。
- 新增 `scripts/seeds/curation/navigation_channels_seed.py`，可校验当前航道 JSON，并可只读检查 `/Users/hj/Documents/河道数据/revier.zip` 的 shapefile 组成。
- 新增 `scripts/seed_data/test/test_scenarios.json`，test profile 改为配置驱动，只生成 `TEST_*` / `TEST-FR-*` 数据。
- 更新 Makefile、Docker entrypoint、README、部署文档、验收文档、前端 README 和相关测试引用。

## 当前结构

- `scripts/seeds/cli.py`：唯一对外 seed CLI。
- `scripts/seeds/profiles.py`：profile dispatch 与 `demo -> local-demo` 别名。
- `scripts/seeds/production.py`：production 导入顺序。
- `scripts/seeds/loaders/`：只读 production curated 数据导入。
- `scripts/seeds/demo/`：local-demo reset、外部配置强校验、demo experience seed。
- `scripts/seeds/test/`：production base 后追加测试夹具。
- `scripts/seeds/curation/`：清洗工具，输入原始附件，输出 curated JSON。
- `scripts/seeds/validation/`：本地验收和基础验收。

## 校验结果

- 航道 JSON 计数保持现有验收口径：104 条航道、95 条边界、200 条航段、294 条 source audit。
- `revier.zip` 只读检查结果：57 个文件、9 组 `.shp/.dbf/.shx/.prj/.cpg` 等 shapefile 组件、10 个 shapefile group。
- root `scripts/` 下已无 `seed_*.py`。
- 已执行：

```bash
.venv/bin/python -m compileall -q scripts/seeds tests/test_seed_profiles.py tests/test_navigation_channels.py tests/test_seed_local_private_config.py tests/test_address_freight_seed_round4.py tests/test_vessel_seed_round5.py
.venv/bin/python -m pytest tests/test_seed_profiles.py tests/test_navigation_channels.py tests/test_seed_local_private_config.py tests/test_address_freight_seed_round4.py tests/test_vessel_seed_round5.py
.venv/bin/python -m scripts.seeds.curation.navigation_channels_seed --source-zip /Users/hj/Documents/河道数据/revier.zip
```

结果：`31 passed`，编译检查通过，航道 curation 只读检查通过。

## 保留边界

- `.env.local` 未读取、未打印、未修改；local-demo 仍通过 `scripts/seeds/loaders/local_private_config.py` 强校验本地地图、模型、ES、轨迹、COS 等配置。
- `revier.zip` 未提交，当前仅作为 curation 工具的只读输入。
- 原始货品、运单、地址、船舶附件仍不进入仓库；生产 seed 只读取 curated JSON/result data。

## 下一步

- 在本地允许重置库的环境下分别运行 `--profile production`、`--profile local-demo`、`--profile test` 做全链路执行验收。
- 若后续需要重新清洗航道，扩展 `navigation_channels_seed.py` 的 shapefile 解析逻辑，并保持输出 JSON schema 与当前 production loader 兼容。
