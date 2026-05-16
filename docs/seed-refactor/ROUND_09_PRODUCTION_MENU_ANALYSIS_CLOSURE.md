# Round 09 生产化菜单与分析闭环收口

## 本轮完成

- 将生产菜单调整为分析平台式信息架构：经营总览、数据资产中心、分析中心、数据质量与治理、系统管理。
- 同步更新前端 fallback 菜单和 route meta，后端菜单失败时不再退回旧业务域结构。
- `ANALYSIS_ALL_DAILY` 成功后会回填所有子任务的最近运行状态和结果摘要。
- 船舶城市热力改为读取真实 `vessel_ais_snapshot` / `vessel_latest_position_snapshot` 聚合。
- 船舶流向在缺少历史 AIS/轨迹源时明确标记不可计算，不生成假流向。
- 新增生产船货适配预计算任务，基于真实 `FR-TMS-*` 货源和最新 AIS 快照生成 `PRODUCTION_ANALYSIS`。
- AIS 城市/航道态势优先使用最新入库全量快照；如果内存缓存是旧空结果，会自动丢弃并重算快照态势。
- 补齐分析来源/需求/供给/不可计算原因字典项：`PRODUCTION_ANALYSIS`、`AIS_LATEST_POSITION`、`TMS_PRODUCTION_FREIGHT`、`TRUSTED_PROFILE` 等。

## 本地生产库验证结果

- production seed 后数据量：货源 4081、节点 1181、船舶 71831、标准货品 169、航道 104、行政区划 3244。
- demo/test 隔离：`FR-DEMO-*`、`TEST-FR-*`、`LOCAL_DEMO`、`TEST_FIXTURE` 均为 0。
- 最新 AIS 快照：扫描 71831 艘，入库定位约 5.4 万艘，失败批次 0。
- 生产船货适配预计算：20 条 `PRODUCTION_ANALYSIS`，候选船 1200 条。
- 全量分析任务：`ANALYSIS_ALL_DAILY` 输出 6913 行；所有子任务均已回填最近运行状态。
- AIS 页面：城市态势和航道态势均可从入库全量快照展示，不再因旧缓存显示空态。

## 本地生产库运行指令

在 `/Users/hj/Documents/paltform_data_V2/inland-shipping-platform` 下执行：

```bash
.venv/bin/python -m scripts.seeds.cli --profile production
.venv/bin/python -m app.tasks.vessel_candidate_tasks
.venv/bin/python -c "from app.tasks.analysis_tasks import run_analysis_job; print(run_analysis_job('ANALYSIS_ALL_DAILY', '2026-05-15', '2026-05-16', True, {'triggered_by':'manual_production_refresh'}))"
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

前端在 `/Users/hj/Documents/paltform_data_V2/frontend` 下执行：

```bash
pnpm run dev
```

如需刷新实时 AIS 全量快照，确保本地私有 ES 配置有效后执行：

```bash
.venv/bin/python -c "from app.tasks.vessel_position_tasks import precompute_ais_situation_task; print(precompute_ais_situation_task())"
```

## 线上运行方式

线上只运行 production seed 和生产分析/预计算任务：

```bash
python -m scripts.seeds.cli --profile production
celery -A app.tasks.celery_app.celery_app worker -Q analysis,freight_ai,vessel_ai
celery -A app.tasks.celery_app.celery_app beat
```

线上不读取 `.env.local`，不加载 demo/test profile，不导入原始清洗附件或中间清洗文件。

## 验证命令

```bash
.venv/bin/python -m compileall app/modules/vessel/ais/methods.py app/modules/analysis/statistics.py app/tasks app/modules/analysis scripts/seeds/loaders
.venv/bin/python -m pytest tests/test_analysis_vessel_facts_round9.py tests/test_seed_profiles.py tests/test_vessel_candidate_analysis.py tests/test_vessel_spatial_analysis.py -q
pnpm run type-check
```

## 遗留风险

- 当前地图 JS 仍可能报高德 key 域名不匹配，需要在高德控制台为本地/线上域名配置正确白名单或替换对应 key；本轮没有提交任何私有 key。
- 船舶流向依赖历史 AIS/轨迹源。未接入真实历史轨迹前，系统只展示不可计算原因，不生成模拟船舶流向。
- 部分真实船位缺少城市边界，页面会以缺失清单和点位聚合提示，不伪造城市 polygon。
