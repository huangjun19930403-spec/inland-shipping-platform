# Round 6 航线与演示/测试 Seed 重建

## 本轮完成

- 将 `scripts/seeds/demo.py` 改为真正的 demo profile orchestrator：先重置本地库、执行 production seed、导入本地私有配置、做外部连通性检查，再只追加新的体验链数据。
- 将 `scripts/seed_local_demo.py` 收缩为兼容包装，继续支持 `--profile local-demo`，实际转发到 `scripts.seeds.demo.seed_demo()`。
- 从 demo 执行链移除旧样例入口：不再调用 `seed_foundation_samples.py`、`seed_vessel_samples.py`、`seed_freight_samples.py`、`seed_route_samples.py`。
- 新增 `scripts/seed_data/demo/demo_scenarios.json`，demo 场景固定引用 Round 4/5 生产节点、生产通航约束和生产货品：
  - 节点：太仓、江阴、南京龙潭、芜湖朱家桥、长兴、常州。
  - 约束：江阴桥区净空、常州奔牛船闸、太仓水深。
  - 航线：`DEMO_ROUTE_TAICANG_WUHU`、`DEMO_ROUTE_TAICANG_NANJING`、`DEMO_ROUTE_CHANGXING_WUHU`。
- 改造 `scripts/experience_seed`，场景、航线、节点不再硬编码旧 `NODE_SUZHOU_*` 等样例编码，改为读取 demo config。
- 保留 demo 业务体验链：`FR-DEMO-*`、`FCA-DEMO-*`、`DEMO_ROUTE_*`、`DEMO_AIS_*`、`LOCAL_DEMO`。
- 新增 test profile overlay：production base 后追加 `TEST_ROUTE_TAICANG_WUHU` 和 `TEST-FR-0001`，不创建 `FR-DEMO-*` 或 `LOCAL_DEMO` 数据。
- 补齐字典项：`SOURCE_TYPE.LOCAL_DEMO`、`SOURCE_TYPE.TEST_FIXTURE`、`ANALYSIS_SOURCE_LAYER.LOCAL_DEMO`、`ANALYSIS_SOURCE_LAYER.TEST_FIXTURE`，并补充 `ROUTE_PLAN_TYPE` 对应项。
- 更新前端 README、验收文档和 E2E 错误提示：需要演示链路运行 `--profile demo/local-demo`，需要稳定夹具运行 `--profile test`，production 不再默认承担演示数据职责。

## 变更文件

- `scripts/seeds/demo.py`
- `scripts/seed_local_demo.py`
- `scripts/seeds/test_profile.py`
- `scripts/seeds/test_fixtures.py`
- `scripts/seed_data/demo/demo_scenarios.json`
- `scripts/experience_seed/shared.py`
- `scripts/experience_seed/main.py`
- `scripts/experience_seed/freight.py`
- `scripts/experience_seed/vessel.py`
- `scripts/experience_seed/cleanup.py`
- `scripts/seed_builtin_dicts.py`
- `scripts/verify_local_acceptance.py`
- `tests/test_seed_profiles.py`
- `docs/SEED_AND_INITIALIZATION.md`
- `/Users/hj/Documents/paltform_data_V2/frontend/README.md`
- `/Users/hj/Documents/paltform_data_V2/frontend/docs/TEST_AND_ACCEPTANCE.md`
- `/Users/hj/Documents/paltform_data_V2/frontend/tests/e2e/helpers.ts`
- `/Users/hj/Documents/paltform_data_V2/frontend/tests/e2e/vessel-management.spec.ts`
- `/Users/hj/Documents/paltform_data_V2/frontend/tests/e2e/vessel-node-route-analysis.spec.ts`
- `/Users/hj/Documents/paltform_data_V2/frontend/tests/e2e/vessel-candidate-analysis.spec.ts`

## 数据输入

本轮没有新增原始附件，也没有清洗新的 CSV。输入只来自前几轮已沉淀的 production curated seed：

- `scripts/seed_data/commodity/*.json`
- `scripts/seed_data/address/business_regions.json`
- `scripts/seed_data/address/transport_nodes.json`
- `scripts/seed_data/navigation_constraints/constraint_points.json`
- `scripts/seed_data/vessel/production_vessels.json`
- `scripts/seed_data/freight/tms_freights.json`

## 隔离边界

- production runner 继续只读取生产结果数据，不导入 demo/local/sample 层。
- demo runner 复用 production base，但只追加带明确 demo 标识的数据。
- test profile 复用 production base，只追加 `TEST_*` / `TEST-FR-*` 小型夹具。
- demo cleanup 只删除 demo 航线、demo 货源、demo AIS/空间观测/候选分析，不删除 `FR-TMS-*` 或生产船舶主档。

## 校验结果

- `demo_scenarios.json` 引用的节点、约束、区域和货品均能在 production curated seed 中找到。
- 静态测试确认 demo runner 不再调用旧样例脚本。
- 静态测试确认 test fixture 文件不生成 `FR-DEMO-*` 或 `LOCAL_DEMO` 数据。
- 已执行：

```bash
.venv/bin/python -m pytest tests/test_seed_profiles.py tests/test_vessel_seed_round5.py
.venv/bin/python -m compileall -q scripts/seeds scripts/experience_seed scripts/seed_local_demo.py scripts/verify_local_acceptance.py
```

结果：`17 passed`，编译检查通过。

## 遗留风险

- 本轮未实际重置数据库跑完整 `--profile demo`，因为该 profile 需要本地 `.env.local` 外部服务配置和连通性检查。静态和编译校验已覆盖执行边界、配置引用和入口导入风险。
- `experience_seed` 中部分历史描述仍保留 local-demo 体验语义，属于数据说明，不再作为生产来源。
- 旧 `seed_*_samples.py` 文件仍保留在仓库中作遗留兼容代码，但已经从 demo/test profile 执行链移除，并有静态测试防止重新接入。

## Round 7 下一步

- 在干净本地库分别执行 `--profile production`、`--profile demo/local-demo`、`--profile test`。
- 校验 production 后无 `FR-DEMO-*`、`FR-LOCAL-*`、`DEMO_ES_MIRROR`、`LOCAL_DEMO`、测试夹具数据。
- 校验 demo 后至少 42 条 `FR-DEMO-*`、42 条 `FCA-DEMO-*`、3 条 `DEMO_ROUTE_*`，候选分析覆盖货源、节点、航线、区域、手工和样本集合场景。
- 校验 test 后存在 `TEST_ROUTE_TAICANG_WUHU` 与 `TEST-FR-0001`，且无 `FR-DEMO-*` 和 `LOCAL_DEMO`。
- 更新最终 seed 初始化与部署验收清单，形成生产上线前的全链路验收文档。
