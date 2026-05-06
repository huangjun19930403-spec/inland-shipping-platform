# Analysis Statistics Tasks

## 任务体系

数据分析统计任务由 API、Celery Worker、Redis broker 和 Celery Beat 组成。

- API 负责读取事实结果、展示任务定义、创建手动运行记录并投递 Celery。
- Worker 执行 `app.tasks.analysis_tasks.run_analysis_job`，调用 `AnalysisStatisticsService` 聚合并写入事实表。
- Beat 定时触发 `ANALYSIS_ALL_DAILY`，默认补算昨天，可通过环境变量调整。
- Redis 用作 Celery broker/result backend，不保存业务结果。

运行状态统一为：

- `QUEUED`：API 已创建运行记录并投递队列。
- `RUNNING`：Worker 已开始执行。
- `SUCCESS`：任务成功完成。
- `PARTIAL_SUCCESS`：编排任务中存在失败子任务，但整体链路完成。
- `FAILED`：任务失败，错误写入 `analysis_job_run.error_message`。

## 任务清单与口径

### ANALYSIS_FREIGHT_DAILY

- 模块：货源分析。
- 源表：`freight`、`freight_source_inbound`、`freight_candidate`。
- 目标表：`fact_freight_daily`。
- 日期字段：`freight.published_at` 优先，否则 `freight.created_at`。
- 过滤条件：`freight.deleted_at is null`，且 `status_code != DRAFT`。
- 聚合口径：按日统计货源量、确认量、候选量、来源接入量、总吨位、预估金额、平均单价。

### ANALYSIS_FREIGHT_FLOW_DAILY

- 模块：流向分析。
- 源表：`freight`、`transport_node`。
- 目标表：`fact_freight_flow_daily`。
- 日期字段：同货源日统计。
- 过滤条件：同货源日统计，且起点和终点节点存在。
- 聚合口径：按日期、起点、终点、标准货品聚合货源量、吨位、平均运价。

### ANALYSIS_FREIGHT_COMMODITY_DAILY

- 模块：货源分析。
- 源表：`freight`、`commodity_standard`、`commodity_type`、`commodity_category`。
- 目标表：`fact_freight_commodity_daily`。
- 日期字段：同货源日统计。
- 过滤条件：同货源日统计，且标准货品存在。
- 聚合口径：按日期、货品分类、货品类型、标准货品聚合货源量、吨位和平均运价。

### ANALYSIS_FREIGHT_PRICE_DAILY

- 模块：运价分析。
- 源表：`freight`、`analysis_bucket_definition`。
- 目标表：`fact_freight_price_daily`。
- 日期字段：同货源日统计。
- 过滤条件：同货源日统计，且 `freight.unit_price` 不为空。
- 聚合口径：按日期和价格桶统计货源量、吨位、最低价、最高价、平均价。

### ANALYSIS_FREIGHT_CITY_DAILY

- 模块：区域分析。
- 源表：`freight`、`transport_node`、`admin_region`、`region_city_relation`。
- 目标表：`fact_freight_city_daily`。
- 日期字段：同货源日统计。
- 过滤条件：同货源日统计，且起点或终点能映射到城市。
- 聚合口径：按日期和城市统计货源热度、入流、出流、吨位，并记录城市主业务区域。

### ANALYSIS_SHIP_DAILY

- 模块：船舶分析。
- 源表：`ship_profile`、`ship_capacity`、`ship_operation`。
- 目标表：`fact_ship_daily`。
- 日期字段：统计日使用任务日期范围内每一天。
- 过滤条件：已 seed 或导入的船舶主档；活跃口径来自本地运营样例。
- 聚合口径：按日期、船型、船龄桶、载重桶统计船舶量、活跃船舶、总载重吨。

### ANALYSIS_SHIP_CITY_DAILY

- 模块：区域分析。
- 源表：ES 船位历史；本地无 ES 时使用确定性样例源。
- 目标表：`fact_ship_city_daily`。
- 日期字段：船位事件时间；本地样例按任务日期逐日生成。
- 过滤条件：有 MMSI 和城市坐标的数据。
- 聚合口径：按日期和城市统计活跃船舶热度，样例数据标记 `data_version=LOCAL_SAMPLE`。

### ANALYSIS_SHIP_FLOW_DAILY

- 模块：流向分析。
- 源表：同一 MMSI 的城市迁移序列；本地无 ES 时使用确定性样例源。
- 目标表：`fact_ship_flow_daily`。
- 日期字段：迁移发生日期。
- 过滤条件：同一 MMSI 有连续不同城市节点。
- 聚合口径：按日期、起点城市、终点城市统计船舶数、航次数和载重吨。

### ANALYSIS_REGION_DAILY

- 模块：区域分析。
- 源表：`fact_freight_city_daily`、`region_city_relation`、`region`。
- 目标表：`fact_region_daily`。
- 日期字段：城市事实表 `stat_date`。
- 过滤条件：只使用城市主区域关系，不从区域 polygon 重新计算。
- 聚合口径：按日期和业务区域汇总货源量、吨位、入流、出流、热度。

### ANALYSIS_ALL_DAILY

- 模块：全部编排。
- 源表：以上任务的全部源表。
- 目标表：以上任务的全部事实表。
- 日期字段：由请求或定时调度传入。
- 聚合口径：按固定顺序执行货源、船舶、城市、流向、区域和运价任务，用于每日调度和一键补算。

## API

- `GET /analysis/tasks`：任务定义列表，支持 `module_code`、`enabled`、分页。
- `GET /analysis/tasks/{job_code}`：任务详情，含源表、目标表、默认参数和最近运行记录。
- `POST /analysis/tasks/{job_code}/trigger`：手动触发任务。
- `GET /analysis/tasks/{job_code}/runs`：指定任务运行记录。
- `GET /analysis/jobs`：全部运行记录。
- `GET /analysis/jobs/{job_run_id}`：运行详情。

手动触发 body：

```json
{
  "date_from": "2026-05-05",
  "date_to": "2026-05-05",
  "force_rebuild": true,
  "parameters_json": {}
}
```

## 启动方式

本地初始化：

```bash
alembic upgrade head
python -m scripts.seed_system_init
python -m scripts.verify_local_acceptance
```

API：

```bash
uvicorn main:app --reload
```

Worker：

```bash
celery -A app.tasks.celery_app:celery_app worker -Q analysis -l info
```

Beat：

```bash
celery -A app.tasks.celery_app:celery_app beat -l info
```

Docker Compose 中应同时启动 API、Redis、`analysis-worker` 和 `analysis-beat`。

## 环境变量

- `CELERY_BROKER_URL`：本机默认 `redis://127.0.0.1:6379/0`，Docker Compose 覆盖为 `redis://redis:6379/0`。
- `CELERY_RESULT_BACKEND`：本机默认 `redis://127.0.0.1:6379/1`，Docker Compose 覆盖为 `redis://redis:6379/1`。
- `ANALYSIS_CELERY_EAGER`：本地测试可设为 `true`，让任务同步执行。
- `ANALYSIS_DEFAULT_DAILY_CRON`：每日调度时间，默认 `30 1 * * *`。

## Seed 与本地样例

`scripts.seed_analysis_samples` 先 seed `analysis_job_definition`、指标和分桶，再从已 seed 的 `freight`、`ship_profile` 等真实业务样例聚合生成事实表。船舶城市热力和船舶流向在未接入 ES 的本地环境使用确定性样例源，结果标记 `LOCAL_SAMPLE`，保证本地调试和验收可重复。
