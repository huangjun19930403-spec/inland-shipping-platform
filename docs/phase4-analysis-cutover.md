# Phase 4：Jobs / Analysis 链路切换说明

## 1. 目标与结果

本阶段只做一件事：让统计实现和分析输出由新主链接管。

已完成：
- `app/jobs/*` 从旧 `app/tasks/stat_tasks.py` 脱离，成为真实统计实现。
- `app/domain/analysis/service.py` 的手动重算入口改为直接调用 `app/jobs/*`。
- `ingestion` / `consumer` / `scheduler` / `celery` 的统计触发改为调用新 jobs。
- 旧 `stat_tasks` 主实现迁移到 `app/tasks/legacy/stat_tasks_legacy.py`。
- `app/tasks/stat_tasks.py` 仅保留 deprecated 兼容桥接，不再承担核心逻辑。

## 2. 统计能力归属（Job 维度）

### 2.1 货源统计

负责人文件：`app/jobs/cargo_stats.py`

覆盖能力：
1. 货源热力统计（`_stat_cargo_city_heatmap`）
2. 货源趋势统计（`_stat_cargo_daily`）
3. 货品排行统计（`_stat_cargo_commodity`）
4. OD 流向统计（`_stat_cargo_od`）
5. 渠道质量统计（`_stat_cargo_channel`）

主入口：
- `run_cargo_stats(stat_date)`：重算指定日期货源统计。

### 2.2 船舶统计

负责人文件：`app/jobs/ship_stats.py`

覆盖能力：
1. 船舶区域热力快照（`_compute_ship_region_snapshot`）
2. 船舶城市热力快照（`_compute_ship_city_snapshot`）
3. 载重吨分布快照（`_compute_ship_dwt_snapshot`）
4. 船龄分布快照（`_compute_ship_age_snapshot`）

主入口：
- `run_ship_dynamic_stats()`：区域 + 城市热力快照
- `run_ship_static_stats()`：载重吨 + 船龄快照
- `run_ship_stats()`：四类快照全量重算

### 2.3 区域计算任务

负责人文件：`app/jobs/region_compute.py`

- `run_region_compute()`：委托 `run_ship_dynamic_stats()`，用于区域/城市热力重算任务化入口。

## 3. 分析接口归属（Analysis Service 维度）

负责人文件：`app/domain/analysis/service.py`

- 货源热力接口：`get_cargo_heatmap`
- 货源趋势接口：`get_cargo_trend`
- 货品排行接口：`get_cargo_commodity_rank`
- OD 分析接口：`get_cargo_od_stats`
- 船龄分布接口：`get_ship_age_distribution`
- 载重分布接口：`get_ship_dwt_distribution`
- 区域热力接口：`get_ship_region_heatmap`
- 城市热力接口：`get_ship_city_heatmap`

手动触发入口：
- `run_daily_stats` -> `app/jobs/cargo_stats.run_cargo_stats` + `app/jobs/ship_stats.run_ship_stats`
- `run_ship_stats` -> `app/jobs/ship_stats.run_ship_stats`

## 4. 统计口径

### 4.1 货源口径

统一过滤条件（`app/jobs/cargo_stats.py::_cargo_base_filters`）：
- `deleted_at IS NULL`
- `record_status = 'ACTIVE'`
- `analysis_status = 'READY'`
- `is_test_data = 0`
- `status IN ('PENDING', 'CONFIRMED')`
- `created_at` 落在统计日期

说明：
- 先清理当日分区行，再重算写入，避免历史脏行残留。
- 货源趋势来自 `cargo_stat_daily`。
- 热力/排行/OD/渠道均按当日数据重算。

### 4.2 船舶口径

统一过滤条件（`app/jobs/ship_stats.py::_vessel_base_filters`）：
- `vessel.data_status = 1`
- `vessel.is_deleted = 0`

说明：
- 区域热力：优先 `current_region_id`，其次节点主归属区域，最后经纬度落区。
- 城市热力：优先节点城市，再用 `current_city_code`，最后经纬度最近城市质心。
- 载重分布：按固定 DWT 桶重算。
- 船龄分布：按 `当前年份 - build_year` 桶重算。

## 5. 旧任务处理

### 5.1 已迁移到 legacy

- `app/tasks/legacy/stat_tasks_legacy.py`（原 `app/tasks/stat_tasks.py` 全量旧实现）

### 5.2 保留但降级（Deprecated Bridge）

- `app/tasks/stat_tasks.py`
  - 仅保留兼容函数名：
    - `refresh_cargo_stats`
    - `refresh_vessel_static_stats`
    - `refresh_vessel_dynamic_stats`
    - `refresh_all_vessel_stats`
    - `daily_stat_job`
  - 以上函数全部转发到 `app/jobs/*`，并记录 deprecated 警告。

### 5.3 主链切断结果

下列主链文件已不再直接依赖旧 `stat_tasks` 实现：
- `app/domain/analysis/service.py`
- `app/api/v1/ingestion/cargo.py`
- `app/domain/vessel/service.py`
- `app/consumers/vessel_dynamic_consumer.py`
- `app/consumers/tms_cargo_consumer.py`
- `app/tasks/scheduler.py`
- `app/tasks/celery_app.py`

## 6. 当前统计主链入口

1. API 手动触发：
   - `/api/v1/analysis/run-stats` -> AnalysisService -> `run_cargo_stats` + `run_ship_stats`
   - `/api/v1/analysis/run-stats/ship` -> AnalysisService -> `run_ship_stats`
2. 写入事件触发：
   - 货源写入后 -> `run_cargo_stats`（background task）
   - AIS 动态更新后 -> `run_ship_dynamic_stats`（30s 节流）
3. 定时触发：
   - APScheduler `daily_stats_job` -> `run_cargo_stats` + `run_ship_stats`
   - Celery Beat -> `app.jobs.cargo_stats.daily_stats_job`
