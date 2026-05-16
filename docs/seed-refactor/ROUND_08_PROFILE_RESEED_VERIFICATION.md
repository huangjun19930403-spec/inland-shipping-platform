# Round 8 Profile Reseed Verification

## 本轮完成

- 本地库已重新执行 `local-demo` seed：先重置本地 SQLite，再导入生产 curated 数据、`.env.local` 私有配置、demo 货源/航线/AIS/候选分析，并补跑分析事实。
- `production`、`local-demo`、`test` 三条 profile 已用独立数据库验证边界，不再靠旧样例 seed 伪造主数据。
- local-demo/test 现在都从生产预制数据中抽取基础数据。船舶维度默认抽样：local-demo 20,000 艘，test 1,500 艘；线上 production 全量 71,831 艘。
- 船舶列表默认排序调整为优先展示 TMS/TMS+高价值来源、画像完整、联系人/吨位信息更全且中文名可读的档案。
- demo/test 会生成可供页面直接展示的分析事实；production seed 只写生产基础数据和分析任务定义，不写 demo/test 分析事实。

## 本地验证结果

当前本地 `local-demo` 库：

- `FR-DEMO-*`: 114 条
- `DEMO_ROUTE_*`: 3 条
- `TEST-FR-*`: 0 条
- `TEST_ROUTE_*`: 0 条
- 船舶档案: 20,000 艘
- 成功分析任务: 1 次
- 货源日事实: 14 天
- 船舶城市日事实: 5,180 条

页面验收：

- 工作台显示船舶档案 20,000 艘、机会样本 4,195 条，并显示成功的 `ANALYSIS_ALL_DAILY` 任务，影响行数 18,908。
- 船舶台账首页优先展示 `鑫隆嘉韵`、`顺发96`、`柏源鸿运` 等中文名、高完整度、高吨位档案。
- 航线列表显示 `DEMO_ROUTE_CHANGXING_WUHU`、`DEMO_ROUTE_TAICANG_NANJING`、`DEMO_ROUTE_TAICANG_WUHU`。
- 供需适配分析页面可展示候选船、AIS 镜像、空间快照和分析依据。

## Profile 隔离验证

临时 production 库：

- `FR-TMS-*`: 4,081 条
- `FR-DEMO-*`: 0 条
- `TEST-FR-*`: 0 条
- `DEMO_ROUTE_*`: 0 条
- `TEST_ROUTE_*`: 0 条
- 船舶档案: 71,831 艘
- 运输节点: 1,181 个
- 标准货品: 169 个
- 航道: 104 条
- 分析事实: 0 条

临时 test 库：

- `TEST-FR-*`: 1 条
- `TEST_ROUTE_*`: 1 条
- `FR-DEMO-*`: 0 条
- `DEMO_ROUTE_*`: 0 条
- 成功分析任务: 1 次
- 货源日事实: 7 天
- 船舶城市日事实: 469 条
- 船舶档案: 1,500 艘

## 本地重建命令

正常本地调试和演示：

```bash
cd /Users/hj/Documents/paltform_data_V2/inland-shipping-platform
.venv/bin/python -m scripts.seeds.cli --profile local-demo
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

如果本地演示也要加载全量生产船舶：

```bash
SEED_VESSEL_LIMIT=full .venv/bin/python -m scripts.seeds.cli --profile local-demo
```

前端：

```bash
cd /Users/hj/Documents/paltform_data_V2/frontend
npm run dev
```

自动化测试夹具：

```bash
cd /Users/hj/Documents/paltform_data_V2/inland-shipping-platform
DATABASE_URL=sqlite+aiosqlite:////private/tmp/inland_seed_test.db \
  .venv/bin/python -m scripts.seeds.cli --profile test
```

## 线上生产命令

线上只执行 migration 和 production seed：

```bash
cd /app
alembic upgrade head
SEED_PROFILE=production .venv/bin/python -m scripts.seeds.cli --profile production
```

生产 seed 不读取 `.env.local`，不生成 `FR-DEMO-*`、`LOCAL_DEMO`、`TEST-FR-*`、demo AIS 或 demo/test 分析事实。生产分析事实应由部署后的分析调度或人工触发分析任务生成。

## 验证命令

```bash
env DEBUG=false .venv/bin/pytest tests/test_seed_profiles.py tests/test_seed_local_private_config.py
env DEBUG=false .venv/bin/pytest tests/test_navigation_channels.py tests/test_address_freight_seed_round4.py tests/test_vessel_seed_round5.py
env DEBUG=false .venv/bin/python -m compileall -q app/core/logging.py app/modules/analysis/statistics.py app/modules/vessel/asset/methods.py scripts/seeds
env DEBUG=false .venv/bin/python -m scripts.seeds.validation.local_acceptance
env DEBUG=false DATABASE_URL=sqlite+aiosqlite:////private/tmp/seed_production_profile_check_20260515.db .venv/bin/python -m scripts.seeds.validation.foundation_data_acceptance
```

前端：

```bash
npm run type-check
```

## 遗留风险

- 现有船舶 curated JSON 未在本轮重新生成；本轮已修正未来清洗时的英文标识名优先级问题，并通过列表排序把当前本地展示优先拉到高质量中文档案。
- local-demo 的外部地图、模型、ES、轨迹、COS 连接测试依赖 `.env.local` 和本机网络。当前 seed 会保留并校验配置键，但在无外网/沙箱环境中连接测试可能降级，不阻断本地 demo 数据生成。
